# Synthetic table examples

These numbers and context labels are hand-authored synthetic data for the documented normalized CSV contract. They were not exported from Cadence, evaluated by Spectre, measured on silicon, or supplied by an independent user. No transistor model or PDK is involved.

The candidate contains one below-limit gain and one explicitly failed observation, so `simreview` should return 1 and show two new check failures. The contract requires a separate `point` label for any sweep or iteration identity; `nominal` is explicitly declared for these examples.
