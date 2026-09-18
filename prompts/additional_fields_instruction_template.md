## Additional Jira Fields

The following additional Jira custom fields are configured for this platform: {additional_field_ids}.

1. When you fetch the Jira issue, request these custom fields together with the issue. The "fields" parameter of the
   issue-fetching tool restricts the response to the listed fields, so when you use it, always list the
   standard content fields of the issue (e.g. summary, description and acceptance criteria) in addition to the
   configured custom fields, so no base issue content is lost.
2. Treat the values of these custom fields as part of the issue content (e.g. as acceptance criteria or other
   requirements) and include them in the content you pass to your review or generation tools.

For example, with the custom field `customfield_10101` configured, request:

```text
summary,description,customfield_10101
```
