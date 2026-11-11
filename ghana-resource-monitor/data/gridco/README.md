# Cleaned GRIDCo series (2013-2025)

`gridco_clean_2013_2025.csv`: one value per year and metric, with confidence, source file, PDF page, method, and the values rejected.
`gridco_decisions.csv`: the 15 judgement calls. `build_clean.py`: regenerates both from the raw file (edit its `D` table to change a call).
The raw file is never modified.

## The test that settled most conflicts
Loss volume (GWh, audited) divided by loss percentage gives the energy total each report must have used.
It matched one candidate and rejected the other in 2019, 2020, 2021 and 2022, and agrees with the headline in 2015-2018 and 2023.

## Use with confidence
- System peak demand 2013-2025 (13 values, none conflicting). 2020 (3,090 MW) confirmed by two reports.
- Energy transmitted 2014-2023. Transmission loss % 2013-2023 and 2025 (2021 = 5.01%, not 5.15%).
- Line length, transformation capacity, substations (note scope changes with asset ownership).

## Use with a flag
- Energy transmitted 2024 (23,692) and 2025 (25,860): published headlines, but the loss volumes imply roughly 25,000 and 26,900. Unresolved; get the GRIDCo transmission statistics or the Energy Commission energy balance.
- Energy 2013 (12.93 TWh): no cross-check available.
- 2024 loss % (3.8) is a rounded chart label.

## Do not trend
- System availability: 2014, 2018, 2020, 2021 differ between same-year text and later restatements (definition appears to change). 2024 is blank. Do not chart it as a trend until the definition is confirmed with GRIDCo.

## Derived (clean peak series)
Peak demand growth: 6.8% a year 2013-2025; 7.3% a year 2019-2025 and 2022-2025; 8.4% in 2025. Supports 7% as the central case and 5%-8.5% as the range.
