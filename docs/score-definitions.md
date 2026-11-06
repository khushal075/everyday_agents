# Score definitions

| Value | Meaning |
| --- | --- |
| Baseline polarity | (positive word occurrences − negative occurrences) / all matched occurrences; zero when none match |
| Learned probability | Logistic regression's estimated probability for one trained class; not calibrated confidence |
| Accuracy | Correct predictions / all examples |
| Precision | True positives / all predictions assigned to the class |
| Recall | True positives / all actual examples in the class |
| F1 | Harmonic mean of precision and recall |
| Macro F1 | Equal-weight average of class F1 values |
| Support | Number of true examples of the class |
| Coverage | Non-abstained predictions / all examples |
| Covered accuracy | Correct predictions / non-abstained predictions |

Classifier scores are in [0, 1]. Polarity is in [-1, 1] and is not confidence:
one matched word can yield an absolute value of 1. Undefined precision/recall/F1
becomes zero; covered accuracy is null with no covered examples.

For sentiment, macro F1 covers negative, neutral, positive. An uncertain output
counts as a miss for its actual class. The confusion matrix includes an uncertain
prediction column but no uncertain true row. Numeric regression/ranking metrics
are future domain requirements, not implemented classification features.
