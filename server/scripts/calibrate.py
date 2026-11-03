"""Precisão e revocação do interpretador por limiar, num conjunto rotulado.

    uv run python scripts/calibrate.py
    uv run python scripts/calibrate.py --models \
        sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2,intfloat/multilingual-e5-small
    uv run python scripts/calibrate.py --show 0.85,0.10     # os erros num limiar

E-001 (regex), sem varredura, no limiar de produção:

    uv run python scripts/calibrate.py --fixed                      # conjunto 1
    uv run python scripts/calibrate.py --fixed --data eval/sessao.yaml
    uv run python scripts/calibrate.py --dump-captures captures/2026-11-10 > eval/sessao.yaml

`--fixed` compara a main (sem regex), a branch (com regex) e o comparador
(os `examples` de regex/patterns.yaml como frases do catálogo e as
`verb_words` no léxico, sem regex; o catalog.yaml não muda) e mede o custo
da regex por cláusula. `--dump-captures` lista as transcrições salvas com
GO2S_SAVE_UTTERANCES=1, na ordem em que foram faladas, com `expect: TODO`
para preencher com o desfecho anotado ANTES de cada frase.

A prioridade é PRECISÃO: um falso positivo move um robô físico.

    acerto          a saída é exatamente os comandos esperados
    falso positivo  a saída tem comandos e não era para ter, ou são os errados
    precisão        acertos / frases em que o servidor executaria algo
    revocação       acertos / frases que eram comandos

Parada indevida (o servidor para quando não devia) é contada à parte: é um
erro, mas não move o robô. Os limiares só afetam o caminho de embeddings; a
linha "só lexical" mostra o que já passa sem modelo nenhum.
"""

import argparse
import json
import statistics
import sys
import time
from dataclasses import dataclass, field, replace
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.catalog import load_catalog  # noqa: E402
from app.config import Settings  # noqa: E402
from app.interpret.evaluate import STOP, outcome  # noqa: E402
from app.interpret.interpreter import Interpreter, Thresholds  # noqa: E402
from app.interpret.recovery import RegexRecovery  # noqa: E402
from app.interpret.text import words  # noqa: E402

ACCEPTS = (0.60, 0.70, 0.75, 0.80, 0.85, 0.90, 0.95)
MARGINS = (0.00, 0.05, 0.10, 0.15, 0.20)


@dataclass
class Score:
    hits: int = 0
    false_positives: list[str] = field(default_factory=list)
    misses: list[str] = field(default_factory=list)
    wrong_stops: list[str] = field(default_factory=list)
    stop_to_command: list[str] = field(default_factory=list)
    hit_texts: dict[str, list[str]] = field(default_factory=dict)  # texto → métodos
    fp_methods: list[list[str]] = field(default_factory=list)
    stop_hits: int = 0
    stops: int = 0
    positives: int = 0

    @property
    def precision(self) -> float:
        acted = self.hits + len(self.false_positives)
        return self.hits / acted if acted else 1.0

    @property
    def recall(self) -> float:
        return self.hits / self.positives if self.positives else 1.0


def evaluate(interpreter: Interpreter, cases: list[dict], wake_words: list[str]) -> Score:
    score = Score()
    for case in cases:
        expected, text = case["expect"], case["text"]
        got, result = outcome(interpreter, text, wake_words)
        detail = f"{text!r}: esperado {expected}, veio {got}"
        if result.reject_reason:
            detail += f" ({result.reject_reason})"
        if isinstance(expected, list):
            score.positives += 1
        if expected == STOP:
            score.stops += 1
            score.stop_hits += got == STOP
        methods = sorted({clause.method for clause in result.clauses if clause.method})
        if isinstance(got, list):
            if got == expected:
                score.hits += 1
                score.hit_texts[text] = methods
            else:
                score.false_positives.append(f"{detail} [{','.join(methods)}]")
                score.fp_methods.append(methods)
            if expected == STOP:
                score.stop_to_command.append(detail)
        elif isinstance(expected, list):
            score.misses.append(detail)
        if got == STOP and expected != STOP:
            score.wrong_stops.append(detail)
    return score


def production_thresholds(settings: Settings) -> Thresholds:
    return Thresholds(
        settings.tau_accept,
        settings.tau_margin,
        settings.tau_slot_accept,
        settings.tau_slot_margin,
        settings.max_clauses,
        settings.tau_stop_accept,
    )


def comparator_catalog(catalog, patterns_path: Path):
    """E-001, alternativa A: os exemplos do arquivo de padrões viram frases do catálogo."""
    data = yaml.safe_load(patterns_path.read_text(encoding="utf-8")) or {}
    commands = dict(catalog.commands)
    for name, block in (data.get("gestures") or {}).items():
        commands[name] = replace(
            commands[name], examples=commands[name].examples + tuple(block.get("examples") or [])
        )
    verbs = dict(catalog.verbs)
    movement = data.get("movement") or {}
    for verb, extra in (movement.get("verb_words") or {}).items():
        verbs[verb] = verbs[verb] + tuple(extra)
    return replace(catalog, commands=commands, verbs=verbs)


def regex_cost_ms(recovery: RegexRecovery, catalog, cases: list[dict], repeat: int = 50) -> float:
    """p95 do tempo da regex (os dois caminhos) por cláusula, em ms."""
    segmenter = Interpreter(catalog, None)
    clauses = [
        words(clause)
        for case in cases
        for clause in segmenter._segment(catalog.tokenize(case["text"]))
    ]
    samples = []
    for _ in range(repeat):
        for tokens in clauses:
            started = time.perf_counter()
            recovery.match_gesture(tokens)
            recovery.match_movement(tokens)
            samples.append((time.perf_counter() - started) * 1000)
    return statistics.quantiles(samples, n=20)[-1] if len(samples) > 1 else 0.0


def fixed(settings: Settings, catalog, cases: list[dict], embedder) -> None:
    """E-001: main × regex × comparador, no limiar de produção."""
    thresholds = production_thresholds(settings)
    recovery = RegexRecovery.from_file(catalog, settings.regex_patterns_path)
    runs = {
        "main": evaluate(Interpreter(catalog, embedder, thresholds), cases, settings.wake_words),
        "regex": evaluate(
            Interpreter(catalog, embedder, thresholds, recovery), cases, settings.wake_words
        ),
    }
    comparator = comparator_catalog(catalog, settings.regex_patterns_path)
    runs["comparador"] = evaluate(
        Interpreter(comparator, embedder, thresholds), cases, settings.wake_words
    )
    main = runs["main"]
    print(f"\n=== E-001, limiar fixo accept={thresholds.accept} margin={thresholds.margin}")
    print("versão      | acertos  FP  FP(regex)  perdidas  parada→comando  recuperadas  perdeu")
    for name, score in runs.items():
        recovered = [t for t in score.hit_texts if t not in main.hit_texts]
        lost = [t for t in main.hit_texts if t not in score.hit_texts]
        fp_regex = sum("regex" in methods for methods in score.fp_methods)
        print(
            f"{name:11s} |   {score.hits:3d}   {len(score.false_positives):2d}      {fp_regex:2d}"
            f"       {len(score.misses):3d}          {len(score.stop_to_command):2d}"
            f"          {len(recovered):3d}      {len(lost):3d}"
        )
        for line in score.false_positives:
            print(f"    FALSO POSITIVO {line}")
        for line in score.stop_to_command:
            print(f"    PARADA VIROU COMANDO {line}")
        for text in recovered:
            print(f"    RECUPERADA {text!r} [{','.join(score.hit_texts[text])}]")
        for text in lost:
            print(f"    PERDEU {text!r}")
    print(f"\ncusto da regex: p95 {regex_cost_ms(recovery, catalog, cases):.3f} ms por cláusula")


def dump_captures(folder: Path) -> None:
    """As transcrições salvas, na ordem em que foram faladas, prontas para rotular."""
    records = sorted(folder.rglob("*.json"), key=lambda path: path.stat().st_mtime)
    print("# Preencha `expect` com o desfecho anotado ANTES de cada frase.")
    for path in records:
        record = json.loads(path.read_text(encoding="utf-8"))
        text = json.dumps(record.get("transcript_raw") or "", ensure_ascii=False)
        print(f"- {{text: {text}, expect: TODO}}  # {record.get('utterance_id')}")


def main() -> int:
    settings = Settings()
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--data", type=Path, default=ROOT / "eval" / "phrases.yaml")
    parser.add_argument("--models", default=settings.embed_model, help="separados por vírgula")
    parser.add_argument("--show", help="accept,margin: lista os erros neste limiar")
    parser.add_argument("--fixed", action="store_true", help="E-001: main × regex × comparador")
    parser.add_argument("--dump-captures", type=Path, help="pasta de captures/ para rotular")
    args = parser.parse_args()
    if args.dump_captures:
        dump_captures(args.dump_captures)
        return 0

    cases = yaml.safe_load(args.data.read_text(encoding="utf-8"))
    catalog = load_catalog(settings.catalog_path)
    positives = sum(isinstance(case["expect"], list) for case in cases)
    print(f"{len(cases)} frases ({positives} comandos, {len(cases) - positives} negativas/parada)")

    baseline = evaluate(Interpreter(catalog, None), cases, settings.wake_words)
    print(
        f"\nsó lexical (sem embeddings): precisão {baseline.precision:.3f}  "
        f"revocação {baseline.recall:.3f}  falsos positivos {len(baseline.false_positives)}"
    )
    for line in baseline.false_positives:
        print(f"  FALSO POSITIVO {line}")

    from app.interpret.embed import SentenceTransformerEmbedder

    for model in args.models.split(","):
        started = time.perf_counter()
        embedder = SentenceTransformerEmbedder(model, settings.embed_threads)
        load_s = time.perf_counter() - started
        if args.fixed:
            fixed(settings, catalog, cases, embedder)
            continue
        started = time.perf_counter()
        embedder.embed([case["text"] for case in cases])
        embed_ms = (time.perf_counter() - started) * 1000 / len(cases)
        print(f"\n=== {model}  (carga {load_s:.1f}s, {embed_ms:.1f} ms por frase)")
        print(
            "accept margin | precisão revocação | acertos  FP  perdidas  paradas  parada indevida"
        )
        best: tuple[float, float, float, float] | None = None
        for accept in ACCEPTS:
            for margin in MARGINS:
                thresholds = Thresholds(accept, margin, accept, margin, settings.max_clauses)
                score = evaluate(
                    Interpreter(catalog, embedder, thresholds), cases, settings.wake_words
                )
                fps, lost = len(score.false_positives), len(score.misses)
                print(
                    f"  {accept:.2f}   {margin:.2f} |   {score.precision:.3f}     "
                    f"{score.recall:.3f} |   {score.hits:3d}   {fps:2d}     {lost:3d}"
                    f"    {score.stop_hits}/{score.stops}      {len(score.wrong_stops)}"
                )
                # No empate, fica o limiar mais exigente.
                rank = (score.precision, score.recall, margin, accept)
                if best is None or rank >= best:
                    best = rank
        print(
            f"melhor (precisão primeiro, depois revocação): accept={best[3]:.2f} "
            f"margin={best[2]:.2f}  precisão {best[0]:.3f}  revocação {best[1]:.3f}"
        )
        if args.show:
            accept, margin = (float(value) for value in args.show.split(","))
            thresholds = Thresholds(accept, margin, accept, margin, settings.max_clauses)
            score = evaluate(Interpreter(catalog, embedder, thresholds), cases, settings.wake_words)
            print(f"\nerros com accept={accept} margin={margin}:")
            for name, lines in (
                ("FALSO POSITIVO", score.false_positives),
                ("PARADA INDEVIDA", score.wrong_stops),
                ("PERDIDA", score.misses),
            ):
                for line in lines:
                    print(f"  {name} {line}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
