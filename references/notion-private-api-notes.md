# Notion Private API Notes

These notes summarize the fragile parts of writing to Notion through an existing local login.

## Cookie Sources

Default macOS locations:

- Notion desktop partition cookies: `~/Library/Application Support/Notion/Partitions/notion/Cookies`
- Codex in-app browser partition cookies: `~/Library/Application Support/Codex/Default/Partitions/codex-browser-app/Cookies`

Prefer Notion desktop cookies when the user is logged in there. The keychain item often uses:

```bash
security find-generic-password -s "Notion Safe Storage" -a "Notion Key" -w
```

On macOS Chromium/Electron cookies commonly use AES-128-CBC with:

- key: `PBKDF2-HMAC-SHA1(password, "saltysalt", 1003, 16)`
- IV: 16 spaces
- prefix: `v10`
- modern plaintext may start with `SHA256(host_key)` before the actual cookie value

Never print decrypted cookies. Only report names, lengths, or whether decryption succeeded.

## Required Request Pattern

1. Build cookie header from local cookies.
2. Call `getRecordValues` for the parent page with `spaceId` included in the request object when possible.
3. Extract `space_id`/`spaceId` from the parent page value.
4. Add headers:

```text
x-notion-space-id: <space-id>
x-notion-active-user-header: <notion_user_id if available>
notion-client-version: <recent client version>
notion-client-platform: web
```

5. Retry record reads with `spaceId` after discovering the parent `space_id`.

If `getRecordValues` returns a role but no `value`, verify both ID formatting and `spaceId`.

## Transaction Formats

Good flat create/update operation:

```json
{
  "table": "block",
  "id": "new-block-id",
  "path": [],
  "command": "set",
  "args": {
    "id": "new-block-id",
    "version": 1,
    "type": "text",
    "properties": { "title": [["Hello"]] },
    "parent_id": "parent-block-id",
    "parent_table": "block",
    "alive": true,
    "space_id": "space-id"
  }
}
```

Append to a page or parent block:

```json
{
  "table": "block",
  "id": "parent-block-id",
  "path": ["content"],
  "command": "listAfter",
  "args": { "id": "child-block-id", "after": "previous-child-id" }
}
```

Remove an entry from a page content list:

```json
{
  "table": "block",
  "id": "parent-block-id",
  "path": ["content"],
  "command": "listRemove",
  "args": { "id": "child-block-id" }
}
```

Avoid the `pointer` operation shape for this import workflow. It may mutate list membership while failing to create entity records.

## Common Errors

`MemcachedCrossCellError`

- Usually caused by missing `spaceId`/workspace routing.
- Add `spaceId` to request objects and `x-notion-space-id` to headers.

`incomplete_ancestor_path`

- Often caused by wrong operation shape or mismatched block field naming.
- Use flat operations and snake_case block fields.
- Test a minimal page plus one text block before importing many pages.

Parent shows child IDs but child pages have no title/value

- The list append succeeded but page entity creation failed.
- Remove bad child IDs from parent with `listRemove`.
- Recreate pages with random UUIDs and the flat `set` operation.

Browser paste/input failures

- Notion and in-app browser clipboard/file upload can be unreliable.
- Prefer API writing after local login is confirmed.

## Verification

After writing:

1. `getRecordValues` parent and created child pages.
2. Check parent `content` contains the new page IDs in order.
3. Check each child page has a title and nonzero `content` count.
4. Optionally open the Notion page in the browser and search for a few expected titles.
