from __future__ import annotations

import argparse
import pathlib
import re
import shutil
import subprocess
import tempfile


REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
DEFAULT_CONTAINER = "kong-dp"
DEFAULT_SOURCE_DIR = REPO_ROOT / "rag" / "atlasflow-support-kb"
DEFAULT_DECK_FILE = REPO_ROOT / "kong" / "deck" / "kong.yaml"
DEFAULT_RAG_SERVICE_NAME = "ai-orchestrator-rag-after-demo-service"
RUNNER_SCRIPT = REPO_ROOT / "scripts" / "ingest_rag_kb.lua"


def chunk_text(text: str, chunk_size: int = 1100, overlap: int = 150) -> list[str]:
    normalized = "\n".join(line.rstrip() for line in text.splitlines()).strip()
    if not normalized:
        return []

    paragraphs = [part.strip() for part in normalized.split("\n\n") if part.strip()]
    chunks: list[str] = []
    current = ""

    for paragraph in paragraphs:
        candidate = f"{current}\n\n{paragraph}".strip() if current else paragraph
        if len(candidate) <= chunk_size:
            current = candidate
            continue

        if current:
            chunks.append(current)

        if len(paragraph) <= chunk_size:
            current = paragraph
            continue

        start = 0
        while start < len(paragraph):
            end = start + chunk_size
            chunk = paragraph[start:end].strip()
            if chunk:
                chunks.append(chunk)
            if end >= len(paragraph):
                break
            start = max(end - overlap, start + 1)
        current = ""

    if current:
        chunks.append(current)

    return chunks


def build_chunks(source_dir: pathlib.Path) -> list[tuple[str, str]]:
    chunks: list[tuple[str, str]] = []
    for path in sorted(source_dir.glob("*.md")):
        raw = path.read_text()
        for index, chunk in enumerate(chunk_text(raw), start=1):
            labeled = f"Source: {path.name}\nChunk: {index}\n\n{chunk}"
            chunks.append((f"{path.stem}-{index}", labeled))
    return chunks


def run(cmd: list[str], *, capture_output: bool = False) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        cmd,
        check=True,
        text=True,
        capture_output=capture_output,
    )


def resolve_plugin_id_from_deck(
    deck_file: pathlib.Path,
    *,
    service_name: str = DEFAULT_RAG_SERVICE_NAME,
) -> str:
    if not deck_file.exists():
        raise SystemExit(f"Deck file not found: {deck_file}")

    lines = deck_file.read_text().splitlines()
    in_service = False
    service_indent = None
    in_plugins = False
    plugin_indent = None
    in_rag_plugin = False

    for line in lines:
        stripped = line.strip()
        indent = len(line) - len(line.lstrip(" "))

        service_match = re.match(r"- name:\s+(.+)$", stripped)
        if service_match and indent == 2:
            in_service = service_match.group(1) == service_name
            service_indent = indent if in_service else None
            in_plugins = False
            in_rag_plugin = False
            continue

        if not in_service:
            continue

        if service_indent is not None and indent <= service_indent and stripped and not stripped.startswith("- name:"):
            in_service = False
            in_plugins = False
            in_rag_plugin = False
            continue

        if stripped == "plugins:":
            in_plugins = True
            plugin_indent = indent
            continue

        if in_plugins and plugin_indent is not None and indent <= plugin_indent and stripped != "plugins:":
            in_plugins = False
            in_rag_plugin = False

        if not in_plugins:
            continue

        plugin_match = re.match(r"- name:\s+(.+)$", stripped)
        if plugin_match:
            in_rag_plugin = plugin_match.group(1) == "ai-rag-injector"
            continue

        if in_rag_plugin:
            id_match = re.match(r"id:\s+([0-9a-fA-F-]+)$", stripped)
            if id_match:
                return id_match.group(1)

    raise SystemExit(
        f"Could not resolve ai-rag-injector plugin id for service '{service_name}' in {deck_file}"
    )


def ingest_chunks(chunks: list[tuple[str, str]], *, plugin_id: str, container: str, dry_run: bool) -> None:
    if dry_run:
        print(f"Prepared {len(chunks)} chunks for plugin {plugin_id}")
        for name, _ in chunks:
            print(name)
        return

    temp_dir = pathlib.Path(tempfile.mkdtemp(prefix="rag-kb-"))
    try:
        runner_target = "/tmp/ingest_rag_kb.lua"
        run(["docker", "cp", str(RUNNER_SCRIPT), f"{container}:{runner_target}"])

        for name, chunk in chunks:
            local_path = temp_dir / f"{name}.txt"
            local_path.write_text(chunk)
            remote_path = f"/tmp/{name}.txt"
            run(["docker", "cp", str(local_path), f"{container}:{remote_path}"])
            result = run(
                ["docker", "exec", container, "kong", "runner", runner_target, plugin_id, remote_path],
                capture_output=True,
            )
            print(f"{name}: {result.stdout.strip()}")
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


def main() -> None:
    parser = argparse.ArgumentParser(description="Chunk and ingest the fictional AtlasFlow support KB into Kong RAG Injector.")
    parser.add_argument("--source-dir", default=str(DEFAULT_SOURCE_DIR))
    parser.add_argument("--plugin-id")
    parser.add_argument("--deck-file", default=str(DEFAULT_DECK_FILE))
    parser.add_argument("--service-name", default=DEFAULT_RAG_SERVICE_NAME)
    parser.add_argument("--container", default=DEFAULT_CONTAINER)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    source_dir = pathlib.Path(args.source_dir)
    if not source_dir.is_absolute():
        source_dir = (REPO_ROOT / source_dir).resolve()
    if not source_dir.exists():
        raise SystemExit(f"Source directory not found: {source_dir}")

    chunks = build_chunks(source_dir)
    if not chunks:
        raise SystemExit("No KB chunks generated")

    plugin_id = args.plugin_id or resolve_plugin_id_from_deck(
        pathlib.Path(args.deck_file) if pathlib.Path(args.deck_file).is_absolute() else (REPO_ROOT / args.deck_file),
        service_name=args.service_name,
    )
    ingest_chunks(chunks, plugin_id=plugin_id, container=args.container, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
