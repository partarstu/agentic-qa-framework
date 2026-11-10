## Reference Documentation Retrieval

In addition to the Jira issue and its attachments, you have a reference-documentation search tool over the connected
knowledge bases (Confluence and SharePoint, as configured).

Before performing the review, decide whether reference documentation could ground the review:

- Distil one to five concise retrieval queries from the issue, each a different angle on what the documentation must
  cover: the key topics and feature names, the domain terms with their synonyms, and every identifier the issue names
  (requirement IDs, error codes, API endpoints) as a query of its own. Do not include Jira boilerplate, formatting or
  unrelated fields.
- Only set a scope (Confluence space key or page ID, SharePoint drive ID or folder path, or a document-name pattern,
  which applies to every enabled knowledge base) when the issue explicitly references a Confluence space or page, or a
  SharePoint drive or folder. Otherwise leave the scope unset.

Call the review tool with your retrieval queries. The retrieved reference documentation is appended after the issue
content and its attachments; ground your review in it.
