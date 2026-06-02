---
name: notion-private-writer
description: Write Markdown notes or long generated content into Notion using the user's existing local Notion login, especially when Notion browser paste/upload is unreliable. Use when Codex needs to create separate child pages under a Notion parent page, import a folder of .md files into Notion, preserve headings/lists/tables/equations as native-ish blocks, clean failed temporary entries, or troubleshoot Notion private API errors such as missing spaceId, MemcachedCrossCellError, or incomplete_ancestor_path.
---

# Notion Private Writer

Use this skill when the user is already logged into Notion locally and asks Codex to write generated notes into Notion, especially as many child pages rather than one long page.

This skill uses Notion's private web API and local desktop/browser session cookies. Treat it as fragile automation, not an official integration. Never print tokens, cookie values, or decrypted secrets.

## Workflow

1. Prefer official APIs if the user provides a Notion integration token. Use this skill only when no official token is available and the user has already approved writing into their logged-in Notion workspace.
2. Prepare source content as Markdown files. For multi-paper or multi-note tasks, make one `.md` file per target Notion page plus an optional overview file.
3. Identify the Notion parent page ID from the URL. Accept dashed or undashed IDs.
4. Run `scripts/notion_md_import.py` with `--parent-page-id` and `--notes-dir`.
5. Verify with `getRecordValues` or `loadPageChunk` that the parent page contains the created child pages, and that each child page has a title and content blocks.
6. Use browser verification only after API verification; Notion frontends can lag or time out.

## Import Script

Use the bundled script:

```bash
python3 <skill>/scripts/notion_md_import.py \
  --parent-page-id <notion-page-id> \
  --notes-dir /path/to/markdown-folder
```

Useful options:

```bash
--cookie-profile notion-desktop     # default; reads Notion desktop cookies
--clean-parent                      # remove all parent children except created pages
--remove-child-id <id>              # remove known bad/test child entries from parent
--dry-run                           # parse and print intended work without writing
--page-title-prefix "SMA | "        # optional title prefix
```

The script intentionally decrypts cookies only in memory and never prints cookie values.

## Critical Details

- Always include `spaceId` in `getRecordValues` requests and `x-notion-space-id` in headers after discovering the parent page's space. Without this, Notion may return `MemcachedCrossCellError` or route to the wrong cell.
- For `saveTransactions`, use the flat operation format:

```json
{
  "table": "block",
  "id": "block-id",
  "path": [],
  "command": "set",
  "args": { "id": "block-id", "type": "text", "...": "..." }
}
```

Do not use `{ "pointer": { ... } }` for this workflow. It can update list fields but fail to create block entities.

- New block values should use Notion's private API field names as returned by `getRecordValues`: `parent_id`, `parent_table`, `created_time`, `last_edited_time`, `space_id`, `created_by_table`, `created_by_id`, `last_edited_by_table`, `last_edited_by_id`.
- Generate random UUIDs for new pages and blocks. Fixed UUIDv5 IDs may be useful for idempotency but can create hard-to-clean half-created entries if an early transaction format is wrong.
- Create page blocks and their child blocks in the same transaction only when the operation format is known good. Verify with a minimal page before a large import.
- To append child pages to a parent page, use `listAfter` on the parent's `content` path.
- To remove bad entries from a parent page without deleting the underlying block, use `listRemove` on the parent's `content` path.

## Markdown Mapping

The bundled script maps:

- `#` first heading to page title
- `##` to Notion `sub_header`
- `###` and deeper headings to `sub_sub_header`
- paragraphs to `text`
- `-` or `*` lines to `bulleted_list`
- `1.` lines to `numbered_list`
- `>` lines to `quote`
- `$$ ... $$` blocks to `equation`
- Markdown tables to `table` plus `table_row`
- fenced code blocks to `code`

For very large imports, split files before importing. Notion transactions with hundreds of operations can work, but smaller pages are easier to verify and recover.

## Troubleshooting

Read `references/notion-private-api-notes.md` when:

- Cookie decryption fails.
- `getRecordValues` works without page values.
- `saveTransactions` returns `incomplete_ancestor_path`.
- The parent page shows links but child pages are blank or missing.
- The user wants the parent page cleaned after accidental long-form paste.
