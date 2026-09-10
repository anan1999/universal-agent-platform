# W8A8 validation

Use this bounded procedure for an 8-bit weight and activation model:

1. Inspect model input and output tensor dtypes and shapes.
2. Verify weight and activation quantization parameters are present and internally consistent.
3. Run the smallest safe runtime validation supported by the assigned environment.
4. Record the runtime and backend actually observed; do not infer backend use from configuration alone.
5. Produce a validation report separating measured evidence, inferred conclusions, and unavailable checks.

Do not download tools, execute unapproved commands, or claim backend validation without runtime evidence.
