"""
Populate the references table in mibo.db from JSON definition files.

Usage (executed from project root):
  python -m scripts.json_pull -memory_path memory -reference_path references

Behavior:
  - Scans all *.json files inside reference_path.
  - For each file, derives reference_type = file_stem with a single trailing 's' removed.
	( assistants.json -> assistant, models.json -> model, prompts.json -> prompt )
  - Each JSON file is expected to map reference_id -> definition (object or string).
  - A row is inserted per entry into the "references" table with:
		reference_id (text), reference_type (text), data (json string)
  - For prompt references ONLY: the JSON value represents a markdown filename stem.
		The markdown file is read from: <memory_path>/prompts/<value>.md
		The stored data object becomes: { "id": <reference_id>, "prompt": <markdown_content> }
		If the markdown file is missing, an error is printed and that prompt is skipped.
  - For other reference types: the JSON value should be an object. If it lacks an 'id', it is added.
  - Existing rows are replaced (idempotent runs).

Exit codes:
  0 on success (even if some individual entries skipped)
  1 on unrecoverable setup errors (e.g., cannot open database directory)
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path
from typing import Dict, Any, Tuple


def parse_arguments() -> Tuple[Path, Path]:
	parser = argparse.ArgumentParser(description="Populate mibo references table from JSON files.")
	parser.add_argument("-memory_path", default="memory", help="Path to memory directory (contains mibo.db and prompts/).")
	parser.add_argument("-reference_path", default="references", help="Path to directory containing reference JSON files.")
	args = parser.parse_args()

	memory_path = Path(args.memory_path).resolve()
	reference_path = Path(args.reference_path).resolve()
	return memory_path, reference_path


def ensure_database(connection: sqlite3.Connection) -> None:
	"""Create the references table if it does not exist."""
	schemas = [
		"""
		CREATE TABLE IF NOT EXISTS "references" (
			sql_id         INTEGER PRIMARY KEY AUTOINCREMENT,
			reference_id   TEXT NOT NULL,
			reference_type TEXT NOT NULL,
			data           TEXT NOT NULL,
			timestamp      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
		);
		""",
		'CREATE UNIQUE INDEX IF NOT EXISTS idx_references_id_type ON "references" (reference_id, reference_type)',
		'CREATE INDEX IF NOT EXISTS idx_references_type ON "references" (reference_type)',
	]
	cursor = connection.cursor()
	for schema in schemas:
		cursor.execute(schema)
	connection.commit()
	cursor.close()


def derive_reference_type(file_path: Path) -> str:
	stem = file_path.stem.lower()
	# Remove a single trailing 's' if present to match singular type naming.
	if stem.endswith('s') and len(stem) > 1:
		return stem[:-1]
	return stem


def load_json(file_path: Path) -> Dict[str, Any]:
	try:
		with file_path.open('r', encoding='utf-8') as f:
			data = json.load(f)
		if not isinstance(data, dict):
			print(f"ERROR: JSON root of {file_path} is not an object; skipping.")
			return {}
		return data
	except json.JSONDecodeError as e:
		print(f"ERROR: Failed to parse JSON file {file_path}: {e}")
	except OSError as e:
		print(f"ERROR: Failed to read file {file_path}: {e}")
	return {}


def read_markdown_prompt(memory_path: Path, prompt_stem: str) -> str | None:
	markdown_path = memory_path / 'prompts' / f"{prompt_stem}.md"
	try:
		with markdown_path.open('r', encoding='utf-8') as f:
			return f.read()
	except FileNotFoundError:
		print(f"ERROR: Prompt markdown file missing: {markdown_path}")
	except OSError as e:
		print(f"ERROR: Unable to read prompt markdown file {markdown_path}: {e}")
	return None


def upsert_reference(connection: sqlite3.Connection, reference_id: str, reference_type: str, data_object: Dict[str, Any]) -> None:
	serialized = json.dumps(data_object, ensure_ascii=False)
	sql = (
		'INSERT OR REPLACE INTO "references" (reference_id, reference_type, data) ' \
		'VALUES (?, ?, ?)'  # noqa: E131 (line continuation clarity)
	)
	cursor = connection.cursor()
	cursor.execute(sql, (reference_id, reference_type, serialized))
	cursor.close()


def process_json_file(connection: sqlite3.Connection, file_path: Path, reference_type: str, memory_path: Path) -> Tuple[int, int]:
	data = load_json(file_path)
	processed = 0
	skipped = 0

	for reference_id, definition in data.items():
		try:
			if reference_type == 'prompt':
				# definition is expected to be a string pointing to markdown stem
				if isinstance(definition, str):
					prompt_content = read_markdown_prompt(memory_path, definition)
					if prompt_content is None:
						skipped += 1
						continue
					data_object = {
						'id': str(reference_id),
						'prompt': prompt_content,
					}
				elif isinstance(definition, dict):
					# If provided as dict, attempt to use 'prompt' field; if it points to a file, load it.
					prompt_value = definition.get('prompt', '')
					if prompt_value and '\n' not in prompt_value and len(prompt_value.split()) == 1:
						# Heuristic: treat single token as filename stem if file exists
						prompt_content = read_markdown_prompt(memory_path, prompt_value)
						if prompt_content is not None:
							definition['prompt'] = prompt_content
					definition['id'] = str(reference_id)
					data_object = definition
				else:
					print(f"ERROR: Unsupported prompt definition type for id {reference_id} in {file_path}; skipping.")
					skipped += 1
					continue
			else:
				if isinstance(definition, dict):
					if 'id' not in definition:
						definition['id'] = str(reference_id)
					data_object = definition
				else:
					print(f"ERROR: Definition for {reference_type} '{reference_id}' in {file_path} is not an object; skipping.")
					skipped += 1
					continue

			upsert_reference(connection, str(reference_id), reference_type, data_object)
			processed += 1
		except Exception as e:  # broad catch to continue processing others
			print(f"ERROR: Failed to process {reference_type} '{reference_id}' from {file_path}: {e}")
			skipped += 1

	return processed, skipped


def main() -> int:
	memory_path, reference_path = parse_arguments()

	if not reference_path.exists() or not reference_path.is_dir():
		print(f"ERROR: reference_path does not exist or is not a directory: {reference_path}")
		return 1

	if not memory_path.exists():
		print(f"ERROR: memory_path does not exist: {memory_path}")
		return 1

	database_path = memory_path / 'mibo.db'

	try:
		connection = sqlite3.connect(database_path)
	except sqlite3.Error as e:
		print(f"ERROR: Cannot open database at {database_path}: {e}")
		return 1

	try:
		ensure_database(connection)

		json_files = sorted(reference_path.glob('*.json'))
		if not json_files:
			print(f"No JSON files found in {reference_path}.")
			return 0

		total_processed = 0
		total_skipped = 0

		for file_path in json_files:
			reference_type = derive_reference_type(file_path)
			processed, skipped = process_json_file(connection, file_path, reference_type, memory_path)
			connection.commit()
			total_processed += processed
			total_skipped += skipped
			print(f"File {file_path.name}: {processed} {reference_type} entries processed, {skipped} skipped.")

		print(f"Done. Total processed: {total_processed}. Total skipped: {total_skipped}.")
		return 0
	finally:
		try:
			connection.close()
		except Exception:
			pass


if __name__ == '__main__':
	sys.exit(main())

