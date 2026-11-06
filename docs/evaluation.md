# Evaluation

Training data has text and one of three labels: negative, neutral, positive.
Uncertain is an abstention from the rules baseline, not a neutral ground-truth class.

The default split is 80/10/10 with seed 42. TF-IDF is fitted within the training
pipeline only. Validation supports model/threshold choices. Test evaluation is
explicit (`--evaluate-test`) and should occur only after those choices are fixed.
The flag does not prevent repeated test inspection; that discipline is the caller's.

`sentiment evaluate --model ... --data ...` evaluates all rows in an independently
provided holdout, without refitting. It does not reconstruct the original split
or verify independence. Passing original training rows would produce optimistic
results and is not a held-out evaluation.

## Reports

Both predictors see the same examples. Accuracy counts uncertain predictions as
misses. Per-class precision, recall, and F1 cover the three sentiment classes;
macro F1 averages those three equally, including any with zero support. Undefined
metrics become zero. Matrix rows are true labels and columns include uncertain.

Coverage is the fraction of non-abstained predictions. Covered accuracy measures
correctness among only those rows and is null when none are covered. Always read
it alongside overall accuracy and coverage. High covered accuracy with low
coverage does not indicate a useful standalone classifier.

The generic ML metric function treats all supplied labels as classes. The domain
evaluator handles abstention explicitly rather than inventing a fourth true class
or converting uncertain to neutral.

## Limits

The included 72 synthetic examples have related wording and tiny held-out splits.
They are not a quality benchmark. The learned predictor has no calibrated
confidence or abstention threshold and need not outperform the baseline.

Real evaluation needs representative, independently labelled data and appropriate
user/group/time splits. Report class support and examine errors. Classifier metrics
do not establish action success: workflow tests independently check execution and
verification. No production acceptance threshold is defined in v0.1.
