"""Learning Engine (Phase 9).

Experience -> Data Cleaning -> Labeling -> Training Dataset
   -> Candidate Training -> Evaluation

Reads Trade Journal / Experience Dataset (Phase 3/4) as a read-only
source, never a new order/broker/risk-mutation path. Produces only
CANDIDATE-status model artifacts (`learning.enums.CandidateModelStatus`)
-- never APPROVED or DEPLOYED, per PROJECT_MASTER_PLAN.md section 11.2/
11.5: a candidate's promotion to those states always requires an
explicit, separate validation phase and human approval, neither of
which this phase performs or bypasses.
"""
