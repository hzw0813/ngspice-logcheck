# A small first pilot

Goal: learn whether importing existing simulation results makes a real review easier. There are no validated independent users yet. This guide is a proposed experiment.

1. Choose one non-sensitive testbench with two known scalar measurements and two revisions. Keep simulator execution and the existing workflow unchanged.
2. Capture each run's combined log and simulator exit status. Record the simulator version and run conditions in your own notes. Use a separate log per run/corner.
3. Write explicit limits in native output units; check both logs and create JSON reports. Inspect missing, duplicated and failed values instead of editing them out.
4. Compare the reports to an HTML review packet. Inspect the limits, deltas, diagnostics and interpretation limits with another engineer.
5. Record installation time, preparation time, unsupported output formats, mistakes caught, and whether the engineer uses it for a second actual review. Compare against the existing spreadsheet/script and CACE, rather than assuming the new tool helps.

Feedback should describe the environment, commands, expected result and one small original reproduction. A voluntarily shared public workflow link can document adoption; an internal test or a downloaded package is not independent adoption. No star, endorsement, or purchase is required.

The larger workbench idea—run history, review annotations and team deployment—is a hypothesis. Building it depends on repeated real use and a budget owner's willingness to pay for a pilot. Contacting people or publishing their work requires separate authorization.
