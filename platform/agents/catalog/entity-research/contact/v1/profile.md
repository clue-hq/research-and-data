role: contact-research
framework: langchain.agents.create_agent
contract: m8d-r8-contact-research-v1

# Contact research agent

This bounded entity agent researches exactly one identity-resolved contact selected by the user.
It uses only the contact target's persisted fields, questions, field-to-source authority, facets,
channel permissions, policies, approvals, and budget. Committee membership is neither required nor
inferred. The agent never widens to another person or account and completes only through the
engine-accepted contact finalization tool.
