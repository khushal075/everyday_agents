# Data

`data/samples/sentiment/feedback.jsonl` contains 72 hand-authored synthetic
English examples: 24 each positive, negative, and neutral. They contain no real
customer records. Related wording makes this a demonstration dataset, not an
independent benchmark or evidence of real-world model quality.

Each row has a non-empty `text` string and a `label`. The JSON schema under
`data/schemas/` documents the shape; the sentiment loader performs runtime checks.
CSV input is also supported through the shared loader.

Raw/private/external/processed dataset directories are ignored. Do not commit
personal data or credentials. Document sources, usage rights, and appropriate
user/group/time separation before introducing real datasets.
