"""The reference library: the documents Clarke can quote.

The user keeps standards, planning criteria, and manuals in
`<projects folder>/Reference documents/`. The modules of this package
read those documents and cache what they derive from them:

- `cache`: the folder's `.gridlens-index/` and its private files;
- `reading`: the files, their text, and their passages;
- `index`: the passages and an inverted index of their words, in
  SQLite;
- `vectors`: the passages' embedding vectors, as float32 matrices;
- `indexer`: brings the index and the vectors up to date;
- `worker`: the background process that runs the indexer;
- `search`: which documents are ready, and their best passages.
"""
