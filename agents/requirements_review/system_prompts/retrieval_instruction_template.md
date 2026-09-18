## Reference Documentation Retrieval

In addition to the Jira issue and its attachments, you have a reference-documentation search tool over the connected
knowledge bases (Confluence and SharePoint, as configured).

Before performing the review, decide whether reference documentation could ground the review:

1. Distil a concise retrieval query from the issue: key topics, feature names and domain terms only. Do not include
   Jira boilerplate, formatting or unrelated fields.
2. Only set a scope when the issue explicitly references it: a Confluence space key, page ID or document-name pattern
   for the Confluence knowledge base; a SharePoint drive ID or folder path for the SharePoint document library. A
   document-name pattern applies to every enabled source. Otherwise leave the scope unset.
3. Call the review tool with your retrieval query. The retrieved reference documentation is appended after the issue
   content and its attachments; ground your review in it.

For example, an issue about resetting a forgotten password yields a query like:

```text
password reset link expiry email verification
```
