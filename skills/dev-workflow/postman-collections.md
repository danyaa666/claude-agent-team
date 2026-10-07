# Postman collections — API test policy

Any task that adds or changes an HTTP API endpoint also adds/updates a Postman collection for
it. This is part of the task's tests (`dev-workflow` Step 2.5), not optional polish — QA checks
for it (`qa-workflow`) and the leader checks for it on review.

## Where they live

One collection file per **epic** — the task's own epic (`B get T-xxx` shows `EPIC <slug>`; it is
the same slug as `.team/epics/<slug>/`). A task with no epic (an unfiled one-off or bug): use the
feature/domain area of the endpoint (`orders`, `auth`, ...) and match an existing file if there is one:

```
postman/<epic-slug>.postman_collection.json
postman/<environment-name>.postman_environment.json   # base_url etc., one per target env
```

One file per epic, not one giant shared collection — parallel dev tasks in *different* epics
then never touch the same file, so no merge-conflict tax on every PR. A new epic = a new file;
say so in the PR.

## Structure: full flow + edge cases, per epic

```
<epic> collection
├── "Full flow"            (a Postman folder — item with a nested "item" array)
│   ├── 1. Create ...       happy path, in dependency order
│   ├── 2. Get/Use ...
│   └── 3. Delete/Close ...
└── "Edge cases"            (a sibling folder)
    ├── <endpoint> - missing required field - 400
    ├── <endpoint> - invalid/expired auth - 401/403
    ├── <endpoint> - not found - 404
    ├── <endpoint> - duplicate/conflict - 409
    └── <endpoint> - boundary value (empty, max length, zero, negative) - ...
```

"Full flow" means what it says: a realistic end-to-end sequence (e.g. create → read → update →
delete), each request's `test` script asserting status code and the response fields that matter,
and capturing anything the next step needs (an id, a token) into a variable. A collection that
only smoke-tests each endpoint in isolation does not satisfy this — chain them.

## Auto variables: never reuse a value across runs, never regenerate mid-flow

The problem: a flow creates a resource with a uniqueness constraint (email, username, slug). Run
the collection twice against a real backend and the second run 409s on data the first run left
behind — flaky-looking failures that are really a test-data bug, not a product bug.

Two mechanisms, pick by scope:

- **One isolated edge-case request, value never reused**: use Postman's built-in dynamic
  variables inline — `{{$timestamp}}`, `{{$randomInt}}`, `{{$guid}}`. They regenerate on every
  use, which is exactly what you want when nothing downstream needs to match it.
- **A multi-request flow where the same value must stay consistent across steps** (sign up with
  an email, then log in with *that same* email): put the generation in the **folder's own
  pre-request script** (not on an individual request, not on the collection) — it then runs
  exactly once, before the folder's first request, for that run of the folder. Every request
  inside references the resulting variable, so the flow is internally consistent; the *next*
  time the folder runs (next CI run, next manual run), it generates a fresh value, so there's
  never a collision with what a previous run left in the database.

```json
{
  "name": "Full flow",
  "event": [
    {
      "listen": "prerequest",
      "script": {
        "type": "text/javascript",
        "exec": [
          "const runId = Date.now().toString();",
          "pm.collectionVariables.set('run_id', runId);",
          "pm.collectionVariables.set('order_email', `qa+${runId}@example.com`);"
        ]
      }
    }
  ],
  "item": [
    {
      "name": "1. Create order",
      "request": {
        "method": "POST",
        "header": [{ "key": "Content-Type", "value": "application/json" }],
        "body": { "mode": "raw", "raw": "{\"email\": \"{{order_email}}\", \"item_id\": 42}" },
        "url": { "raw": "{{base_url}}/orders", "host": ["{{base_url}}"], "path": ["orders"] }
      },
      "event": [
        {
          "listen": "test",
          "script": {
            "type": "text/javascript",
            "exec": [
              "pm.test('201 Created', () => pm.response.to.have.status(201));",
              "const body = pm.response.json();",
              "pm.test('has order id', () => pm.expect(body.id).to.be.a('number'));",
              "pm.collectionVariables.set('order_id', body.id);"
            ]
          }
        }
      ]
    },
    {
      "name": "2. Get order",
      "request": {
        "method": "GET",
        "url": { "raw": "{{base_url}}/orders/{{order_id}}", "host": ["{{base_url}}"], "path": ["orders", "{{order_id}}"] }
      },
      "event": [
        { "listen": "test", "script": { "type": "text/javascript", "exec": [
          "pm.test('200 OK', () => pm.response.to.have.status(200));",
          "pm.test('email matches', () => pm.expect(pm.response.json().email).to.eql(pm.collectionVariables.get('order_email')));"
        ] } }
      ]
    }
  ]
}
```

(`run_id`/`order_email`/`order_id` are declared once, empty, in the collection's top-level
`"variable"` array — that's what makes them collection variables the pre-request script can set
and every request can read via `{{...}}`.)

## Running them

```bash
newman run postman/<epic>.postman_collection.json -e postman/<environment>.postman_environment.json
```

If `newman` (or the Postman app) isn't set up in the project yet, importing and running the
collection by hand is an acceptable substitute for now — say so explicitly in the PR/QA note
rather than silently skipping it, and consider filing a tech-debt task to wire up `newman` in CI.

## What review checks for

- New/changed endpoint with no corresponding collection entry → missing test, same as a missing
  unit test.
- A flow whose steps don't actually chain (hardcoded ids instead of captured variables) → not a
  real flow test.
- A pre-request script on an individual request where the value needs to survive across that
  request and a later one in the same folder → wrong scope, will break the flow; move it to the
  folder.
- No edge-case folder/requests for a non-trivial endpoint → incomplete, per the `dev-workflow`
  test-writing step this file is referenced from.
