# Models and agents

A model maps an input to a prediction. An agent coordinates prediction, a policy
decision, an action, and result verification. In this implementation the model
does not choose tools: a domain policy chooses supported action names, and a tool
component executes them.

SentimentBaseline is a rules-based predictor, not a trained ML model. The learned
predictor wraps TF-IDF and logistic regression. Both can power the same agent.
Training and evaluation take place separately from action execution.

The v0.1 agent executes one bounded cycle. It does not imply an LLM, autonomous
long-running planning, persistent memory, or general-purpose intelligence.
