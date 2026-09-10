# Static metadata contract

For each declared tensor, record its name, shape, dtype, scale, and zero point.
W8A8 evidence requires 8-bit weight and activation declarations plus positive
numeric scales. Report absent fields as unavailable; never infer them.

Separate the report into `Measured Evidence`, `Unavailable Checks`, and
`Conclusion`. Static fixture inspection is measured evidence about metadata,
not evidence that a hardware backend executed the model.
