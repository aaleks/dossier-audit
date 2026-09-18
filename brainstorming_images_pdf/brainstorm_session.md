# Brainstorm Session — Multi-PDF Postmortem Intelligence Architecture

## Purpose

Challenge and explore the architecture for processing a corpus of large PDF postmortems (e.g. 25 postmortems covering a year) and supporting multiple analytical use cases over the same corpus.

This is intentionally a **brainstorm / challenge document**, not a final architecture.

The next agent should feel free to reject the proposed architecture, simplify it, or propose materially different alternatives.

---

# 1. Problem

We have a corpus of potentially large PDF documents.

Example:

- 25 PDF postmortems
- Each PDF may contain:
  - text
  - tables
  - screenshots
  - graphs
  - diagrams
  - timelines
  - technical evidence
  - remediation actions
- PDFs may vary considerably in quality and structure.

We want to process the corpus once and then support multiple analytical use cases.

## Core use case 1 — Corpus summary

Example:

> Summarize these 25 postmortems from 2025.

Desired output could include:

- overall annual summary
- incident count
- severity / impact overview
- major systems affected
- recurring technical themes
- important incidents
- remediation overview

## Core use case 2 — Cross-document intelligence

Example:

> Across these 25 postmortems, identify common patterns of failure. Assess the quality/completeness of the postmortems. Identify recurring technical issues and propose actionable long-term architectural remediation.

Potential output:

- recurring failure patterns
- recurring root causes
- recurring contributing factors
- recurring technical problems
- observability/detection gaps
- postmortem quality weaknesses
- remediation patterns
- architectural weaknesses
- long-term remediation proposals
- evidence supporting each conclusion
- affected incidents/documents
- frequency / prevalence where meaningful

The important point:

**The second use case is not just summarization. It is corpus-level reasoning.**

---

# 2. Main architectural hypothesis

Current hypothesis:

Do NOT simply do:

    25 PDFs
       ↓
    Refine chain
       ↓
    final summary

Instead, create a reusable evidence layer.

Proposed conceptual pipeline:

    PDF corpus
        ↓
    PDF ingestion / parsing
        ↓
    document structure + page references
        ↓
    per-document evidence extraction
        ↓
    structured IncidentRecord[]
        ↓
    semantic representations / embeddings
        ↓
    clustering / similarity / aggregation
        ↓
    user-selected analytical prompt
        ↓
    corpus-level reasoning
        ↓
    evidence-backed report

The same processed corpus should support many future prompts without re-processing all PDFs.

---

# 3. Evidence Record

The PDF should first be converted into a structured representation.

Example:

```json
{
  "incident_id": "PM-017",

  "incident": {
    "date": "...",
    "service": "...",
    "severity": "...",
    "duration": "...",
    "impact": "..."
  },

  "failure": {
    "failure_mode": "...",
    "root_cause": "...",
    "contributing_factors": []
  },

  "detection": {
    "how_detected": "...",
    "detection_delay": "...",
    "monitoring_gaps": []
  },

  "response": {
    "actions": [],
    "response_gaps": []
  },

  "remediation": {
    "immediate": [],
    "preventive": [],
    "long_term": []
  },

  "quality": {
    "missing_root_cause": false,
    "missing_timeline": true,
    "missing_impact": false,
    "missing_remediation": false
  },

  "evidence": [
    {
      "claim": "...",
      "page": 7
    }
  ]
}
```

This should ideally preserve provenance.

A conclusion should be traceable back to:

- document
- page
- section
- potentially bounding box / image / table where relevant

The exact provenance model still needs to be challenged.

---

# 4. Why have an evidence layer?

Potential benefits:

1. Avoid repeatedly processing expensive PDFs.
2. Make downstream prompts more deterministic.
3. Allow multiple analyses over the same corpus.
4. Allow structured aggregation.
5. Enable exact counting/filtering.
6. Enable quality assessment.
7. Preserve evidence and citations.
8. Enable embeddings without embedding the entire raw PDF.
9. Enable evaluation.
10. Enable future analytical use cases.

Potential concern:

The evidence extraction itself may introduce hallucinations or information loss.

Therefore the architecture should not assume:

    PDF → evidence record = perfect truth

The evidence layer should retain enough provenance to verify important claims.

---

# 5. Refine vs Map-Reduce

A traditional Refine approach:

    summary = summarize(PDF1)

    summary = refine(summary, PDF2)
    summary = refine(summary, PDF3)
    ...
    summary = refine(summary, PDF25)

Potential problems:

- order dependence
- difficult parallelization
- evolving summary may lose information
- early mistakes can propagate
- difficult debugging
- difficult reproducibility
- summary may become increasingly compressed

Map-Reduce:

    PDF/chunk 1 → summary 1
    PDF/chunk 2 → summary 2
    ...
    PDF/chunk N → summary N

    summaries
       ↓
    reduce
       ↓
    result

Advantages:

- parallelism
- isolation
- retry individual units
- easier observability
- easier caching
- less order dependence

However, the question remains:

**Is Map-Reduce actually sufficient, or should this be hierarchical?**

---

# 6. Hierarchical summarization hypothesis

For large PDFs:

    PDF
      ↓
    sections
      ↓
    section summaries
      ↓
    chapter/document summaries
      ↓
    PDF summary

Then:

    25 PDF summaries
      ↓
    corpus synthesis

Potential hierarchy:

    PDF
      ├── section 1
      ├── section 2
      ├── section 3
      └── ...

    section summaries
      ↓
    document summary

    25 document summaries
      ↓
    global summary

This avoids sending thousands of chunks to a single final context.

But challenge this assumption.

Questions:

- Are section-level summaries necessary?
- Could a strong long-context model process each PDF directly?
- Could entire PDFs be multimodally processed?
- Does hierarchical summarization introduce information loss?
- Should the hierarchy be semantic rather than based on document headings?
- Should tables/images be handled separately?

---

# 7. LangChain vs LangGraph

Current hypothesis:

LangChain components can be used, but LangGraph may be a better orchestration layer.

Reason:

This is fundamentally a workflow:

    ingest
      ↓
    parse
      ↓
    extract
      ↓
    map
      ↓
    reduce
      ↓
    analyze
      ↓
    validate
      ↓
    report

Potential LangGraph graph:

    START
      ↓
    Load PDFs
      ↓
    Parse / structure
      ↓
    Parallel document processing
      ↓
    Incident records
      ↓
    Build corpus representations
      ↓
    User analysis prompt
      ↓
    Analysis
      ↓
    Validation
      ↓
    Final report

LangGraph advantages potentially include:

- parallelism
- retries
- checkpointing
- state
- observability
- conditional branches
- human-in-the-loop
- long-running workflows

But:

**Do we actually need LangGraph?**

Alternative:

- plain Python
- asyncio
- LangChain Runnable parallelism
- a task queue
- Prefect
- Dagster
- Temporal
- another workflow engine

The next agent should explicitly challenge whether LangGraph is justified.

---

# 8. Do we need an agent?

Current position:

Probably NOT for the core PDF processing.

This looks more like deterministic workflow orchestration than an autonomous agent.

Potential workflow:

    PDF ingestion
       ↓
    extraction
       ↓
    structured evidence
       ↓
    clustering
       ↓
    analytical prompt
       ↓
    report

An agent could potentially be useful later for:

- deciding which analyses to run
- exploring clusters
- drilling into evidence
- generating follow-up questions
- dynamically retrieving supporting evidence
- interactive investigation

But the core pipeline should probably remain deterministic.

Challenge this assumption too.

---

# 9. Embeddings

Important question:

If we already have an EvidenceRecord, why do we need embeddings?

Answer:

The evidence record provides **structured/exact representation**.

Embeddings provide **semantic representation**.

They solve different problems.

Structured representation is good for:

- counting
- filtering
- aggregation
- exact queries
- statistics
- validation

Example:

> How many incidents involved Redis?

Could be answered using structured fields.

Embeddings are useful for:

> Which incidents have similar underlying failure mechanisms?

Two incidents may use different terminology:

    Redis connection exhaustion

    RabbitMQ channel exhaustion

    Kafka consumer saturation

    HTTP connection pool depletion

They may share a deeper semantic pattern:

    resource exhaustion / capacity governance / retry amplification

Embeddings can help identify these semantically similar cases.

---

# 10. What should be embedded?

Do NOT automatically embed:

- entire PDF
- entire raw JSON
- every page
- every chunk

Instead, create semantic representations specifically for analytical purposes.

Possible representations:

## A. Failure representation

Example:

    System: Redis

    Failure mode:
    Connection pool exhaustion.

    Root cause:
    Applications created excessive connections during failover.

    Contributing factors:
    - aggressive retry
    - no connection limits
    - insufficient monitoring

    Architectural weakness:
    Shared Redis infrastructure without workload isolation.

Use for:

> recurring failure pattern discovery

---

## B. Remediation representation

Example:

    Immediate remediation:
    Increase connection limits.

    Preventive remediation:
    Add connection monitoring.

    Long-term remediation:
    Introduce workload-level resource budgets and isolation.

Use for:

> finding repeated or equivalent remediation strategies

---

## C. Incident representation

Combine:

- failure
- impact
- root cause
- contributing factors
- remediation

Use for:

> broad incident similarity

---

## D. Architecture representation

Represent:

- components
- dependencies
- topology
- failure mechanism
- architectural weaknesses

Use for:

> identifying recurring architectural weaknesses

---

# 11. Important embedding principle

Embeddings should not be considered the source of truth.

Potential division of responsibility:

    Structured evidence
           │
           ├── exact aggregation
           ├── filtering
           └── provenance

    Embeddings
           │
           ├── similarity
           ├── clustering
           └── semantic discovery

    LLM
           │
           ├── explain clusters
           ├── infer higher-level patterns
           ├── compare evidence
           └── propose remediation

Conceptually:

**Embedding discovers candidates.**

**LLM explains them.**

**Evidence validates them.**

This division should be challenged.

---

# 12. Do we even need embeddings?

Important alternative.

There are only ~25 documents.

Potential approach:

    25 IncidentRecords
       ↓
    LLM analysis directly

Perhaps embeddings are unnecessary at this scale.

Embeddings become more compelling when:

- corpus becomes hundreds/thousands of incidents
- incidents need retrieval
- similarity search is required
- historical years are accumulated
- interactive investigation is required

Potential alternative:

Use structured taxonomy first:

    failure_category
    component
    root_cause_category
    contributing_factor_category
    architecture_category

Then only add embeddings for discovering patterns not captured by taxonomy.

This may actually be better.

---

# 13. Hybrid approach

Potential strong design:

    EvidenceRecord
         │
         ├── structured taxonomy
         │
         ├── embeddings
         │
         └── provenance
                │
                ▼
          corpus analysis

Use classical code for:

- counts
- frequencies
- filtering
- grouping
- statistics

Use embeddings for:

- semantic similarity
- candidate clusters
- duplicate/near-duplicate remediation
- discovering unexpected relationships

Use LLM for:

- interpretation
- synthesis
- causal-pattern discussion
- architectural reasoning
- report generation

---

# 14. Clustering

Possible pipeline:

    25 incidents
       ↓
    failure embeddings
       ↓
    similarity matrix
       ↓
    clustering
       ↓
    candidate groups

Example:

    Cluster A
      PM1
      PM4
      PM7
      PM11

    Cluster B
      PM2
      PM5
      PM13
      PM21

Then give each cluster to an LLM:

> Analyze these incidents. What common underlying mechanism explains their similarity? Cite the supporting evidence.

Potential issue:

25 points is a very small dataset.

Clustering algorithms may produce unstable or meaningless clusters.

Therefore challenge:

- Do we use clustering at all?
- Is pairwise similarity more appropriate?
- Should an LLM perform thematic grouping?
- Should taxonomy + embeddings be combined?
- How do we validate clusters?

---

# 15. Postmortem quality analysis

Quality should probably be a first-class analysis.

Potential dimensions:

| Dimension | Example |
|---|---|
| Incident description | Is the event clearly explained? |
| Impact | Is business/technical impact quantified? |
| Timeline | Is the timeline complete? |
| Root cause | Is root cause clearly established? |
| Contributing factors | Are secondary causes identified? |
| Detection | Is detection mechanism explained? |
| Response | Are response actions documented? |
| Remediation | Are corrective actions defined? |
| Long-term prevention | Is architectural prevention addressed? |
| Evidence | Are conclusions supported by evidence? |

Could produce a structured quality record:

```json
{
  "timeline": 5,
  "impact": 3,
  "root_cause": 4,
  "detection": 2,
  "remediation": 3
}
```

But numerical scoring should be challenged.

Potential alternative:

Use qualitative categories:

- complete
- partially complete
- missing
- ambiguous
- contradicted

Or use objective checks rather than subjective LLM scores.

---

# 16. Recurring technical issue analysis

Potential example:

25 incidents reveal:

- connection pool exhaustion
- insufficient capacity limits
- retry amplification
- missing saturation alerts
- dependency isolation problems

Instead of treating these as 25 independent incidents, the system should identify higher-level patterns.

Potential hierarchy:

    Incident
       ↓
    Technical issue
       ↓
    Failure mechanism
       ↓
    Architectural pattern
       ↓
    Long-term remediation

Example:

    Redis connection exhaustion
            ↓
    Resource exhaustion
            ↓
    Lack of resource governance
            ↓
    Platform architecture weakness
            ↓
    workload isolation + budgets + saturation-based alerting

The LLM should not automatically jump from symptom to architecture.

The reasoning should remain evidence-backed.

---

# 17. Architectural remediation

This is potentially the most valuable output.

Desired distinction:

## Immediate fix

Example:

    Increase connection limit.

## Preventive fix

Example:

    Add connection monitoring.

## Architectural remediation

Example:

    Introduce workload-level connection budgets,
    isolation, retry governance, and saturation-aware
    traffic management.

The system should look for remediation that addresses **classes of failures**, not merely individual incidents.

Potential output:

    Recurring pattern:
    Resource exhaustion

    Affected incidents:
    PM01, PM04, PM07, PM11, PM19

    Evidence:
    ...

    Current remediation:
    Mostly incident-specific capacity increases.

    Architectural opportunity:
    Introduce standardized resource budgets and
    failure amplification controls.

    Expected scope:
    Platform-wide.

Do NOT claim that a remediation will eliminate incidents unless evidence supports that claim.

---

# 18. Evidence and citations

This is critical.

Every important analytical conclusion should ideally be traceable.

Example:

    Pattern:
    Retry amplification appears in 6 incidents.

    Evidence:
    PM-003 p.7
    PM-008 p.11
    PM-012 p.5
    PM-019 p.9
    ...

Potential evidence hierarchy:

    claim
      ↓
    evidence items
      ↓
    document
      ↓
    page
      ↓
    section / bounding box / image / table

Questions to challenge:

- How granular should provenance be?
- Should page images be retained?
- Should evidence include text snippets?
- How do we cite screenshots?
- How do we prevent citations pointing to an LLM-generated intermediate summary rather than original evidence?
- Should final reports cite original PDFs directly?

---

# 19. PDF multimodal problem

Postmortems may contain:

- screenshots
- graphs
- architecture diagrams
- tables
- dashboards
- timelines rendered as images

Text extraction alone may lose critical information.

Potential ingestion pipeline:

    PDF
      │
      ├── text
      ├── tables
      ├── images
      ├── page rendering
      └── layout information
             ↓
        multimodal analysis
             ↓
        EvidenceRecord

Need to determine:

- when OCR is needed
- when vision models are needed
- whether images should be embedded
- whether page screenshots should be retained
- how to associate visual evidence with page numbers
- whether graphs should be interpreted numerically or descriptively

This is a major architectural area to challenge independently.

---

# 20. Reusability

The corpus should ideally be processed once.

For example:

    2025 corpus
       ↓
    ingestion
       ↓
    evidence store
       ↓
    embeddings
       ↓
    reusable corpus

Then run:

    Prompt A:
    "Summarize all incidents."

    Prompt B:
    "Find recurring failure patterns."

    Prompt C:
    "Assess postmortem quality."

    Prompt D:
    "Find recurring Redis issues."

    Prompt E:
    "Propose long-term architectural remediation."

Without reprocessing the original PDFs.

---

# 21. Potential storage model

Possible PostgreSQL schema:

    documents
    ├── document_id
    ├── filename
    ├── year
    ├── metadata
    └── checksum

    evidence
    ├── evidence_id
    ├── document_id
    ├── page
    ├── section
    ├── claim
    └── source_reference

    incidents
    ├── incident_id
    ├── document_id
    ├── service
    ├── severity
    ├── root_cause
    └── ...

    remediation_actions
    ├── action_id
    ├── incident_id
    ├── type
    └── description

    embeddings
    ├── object_id
    ├── representation_type
    └── vector

Potentially use pgvector.

But do not assume pgvector is necessary from day one.

---

# 22. Caching

This pipeline may be expensive.

Cache at multiple levels:

    PDF hash
       ↓
    extraction cache

    extraction hash
       ↓
    evidence extraction cache

    evidence representation hash
       ↓
    embedding cache

    prompt + evidence version
       ↓
    analysis result cache

This allows:

- prompt changes without reprocessing PDFs
- model changes without re-ingesting
- individual document retries
- reproducibility
- cost control

---

# 23. Evaluation

Potential evaluation layers:

## Extraction evaluation

Did we correctly extract:

- root cause?
- impact?
- timeline?
- remediation?
- evidence?

## Summary evaluation

Does summary cover important incidents?

## Pattern evaluation

Did system identify real recurring patterns?

## Citation evaluation

Do claims correctly point to source evidence?

## Recommendation evaluation

Are architectural recommendations actually supported by the incidents?

Potential golden dataset:

    manually reviewed incidents
          ↓
    expected evidence
          ↓
    expected patterns
          ↓
    expected quality assessment

Could evaluate using MLflow.

---

# 24. MLflow / observability

Potential trace structure:

    batch_run
       │
       ├── document_001
       │    ├── extraction
       │    ├── evidence
       │    ├── embedding
       │    └── summary
       │
       ├── document_002
       │    └── ...
       │
       └── corpus_analysis
            ├── clustering
            ├── pattern_analysis
            ├── quality_analysis
            └── report

Track:

- model
- prompt version
- document ID
- page ranges
- token usage
- latency
- failures
- cache hits
- evaluation results
- analysis version

---

# 25. Alternative architecture A — Long-context LLM

Potentially much simpler:

    25 PDFs
       ↓
    extract / multimodal parse
       ↓
    large-context model
       ↓
    one analytical prompt

Advantages:

- simple
- fewer moving parts
- potentially better global reasoning
- no clustering infrastructure

Problems:

- context limits
- cost
- potentially poor attention over huge corpora
- difficult provenance
- difficult retry/caching
- potentially less reproducible

This should be benchmarked rather than dismissed.

---

# 26. Alternative architecture B — Pure structured analytics

    PDFs
      ↓
    structured evidence
      ↓
    SQL/Python aggregation
      ↓
    LLM synthesis

No embeddings.

Potentially excellent if taxonomy is strong.

Challenge whether embeddings add enough value for only 25 documents.

---

# 27. Alternative architecture C — RAG

    PDFs
      ↓
    chunks
      ↓
    vector DB
      ↓
    retrieve relevant evidence
      ↓
    LLM

Useful for interactive questions.

Potential problem:

RAG may be poor for:

> "Find all recurring patterns across the entire corpus."

Retrieval may only return a subset.

Therefore global corpus analysis may require:

- full corpus representations
- hierarchical summaries
- structured aggregation
- clustering

rather than ordinary top-k RAG.

---

# 28. Alternative architecture D — LLM thematic analyst

    25 evidence records
         ↓
    LLM
         ↓
    themes
         ↓
    evidence retrieval
         ↓
    verification
         ↓
    final report

Potentially simpler than embeddings.

The LLM proposes patterns and then the system retrieves/verifies supporting evidence.

Could be a strong alternative.

---

# 29. Key design principle to challenge

Current assumption:

> Process once into reusable structured evidence, then perform multiple analyses over that representation.

Challenge:

- Is this over-engineering for 25 PDFs?
- Does extraction lose too much information?
- Would a multimodal long-context model be better?
- Should the raw PDF remain available during analysis?
- Should analysis dynamically retrieve original pages?
- Should structured evidence be authoritative or merely an index?
- Should embeddings be generated at all?

---

# 30. Proposed architecture — current working version

```text
                         PDF Corpus
                            │
                            ▼
                 ┌─────────────────────┐
                 │ PDF ingestion        │
                 │ text/table/image     │
                 │ layout/provenance    │
                 └──────────┬──────────┘
                            │
                            ▼
                 ┌─────────────────────┐
                 │ Evidence extraction │
                 │ per document        │
                 └──────────┬──────────┘
                            │
                            ▼
                 IncidentRecord[]
                            │
              ┌─────────────┼─────────────┐
              │             │             │
              ▼             ▼             ▼
        Structured       Semantic       Quality
        fields           embeddings     assessment
              │             │
              │             ▼
              │          similarity /
              │          clustering
              │             │
              └─────────────┼─────────────┘
                            ▼
                   Corpus analysis
                            │
                     user prompt
                            │
              ┌─────────────┼─────────────┐
              ▼             ▼             ▼
          Summary        Patterns      Architecture
                           /Quality      remediation
              │             │             │
              └─────────────┼─────────────┘
                            ▼
                    Evidence-backed
                       final report
```

---

# 31. Questions for the challenging agent

Please challenge the architecture aggressively.

## Complexity

1. Is this architecture unnecessarily complex for only 25 PDFs?
2. What would you build if you had only one week?
3. What components can be removed without materially reducing quality?

## Framework

4. Would you use LangChain?
5. Would you use LangGraph?
6. Would you use neither?
7. Would a workflow engine be more appropriate?

## Summarization

8. Is hierarchical Map-Reduce actually better than a long-context model?
9. When should Refine be used?
10. Should summarization happen per chunk, per section, or per document?

## Evidence

11. What should the canonical EvidenceRecord contain?
12. Should evidence extraction be LLM-based?
13. How do we prevent information loss between PDF and EvidenceRecord?
14. Should the raw PDF remain accessible during downstream analysis?

## Embeddings

15. Are embeddings actually useful with only 25 documents?
16. What exactly should be embedded?
17. Should we embed failures, incidents, remediation, architecture, or all four?
18. Is clustering reliable with such a small dataset?
19. Would semantic search be more useful than clustering?
20. Could an LLM replace embeddings for thematic discovery?

## Quality

21. How should postmortem quality be measured?
22. Should quality use numerical scores?
23. How do we make quality assessment objective and reproducible?

## Architecture analysis

24. How do we distinguish a recurring symptom from a recurring architectural cause?
25. How do we avoid the LLM inventing architectural recommendations?
26. How should recommendations be connected to evidence?

## Multimodal PDFs

27. How should graphs, screenshots and architecture diagrams be handled?
28. Should every PDF page be rendered to images?
29. When should vision models be invoked?
30. How should visual evidence be represented in the EvidenceRecord?

## Provenance

31. How should every claim retain its original PDF/page/source?
32. What is the minimum provenance required for trustworthy output?

## Scale

33. Would your design change for:
    - 25 PDFs?
    - 250 PDFs?
    - 2,500 PDFs?
    - 10 years of postmortems?

34. At what scale would pgvector become worthwhile?

## Evaluation

35. How would you evaluate whether the recurring patterns are actually correct?
36. How would you evaluate architectural recommendations?
37. What golden dataset would you create?

---

# 32. Desired challenge output

Do not simply say whether the architecture is "good."

Instead, provide:

1. **Your proposed architecture**
2. **What you would remove**
3. **What you would add**
4. **What assumptions you disagree with**
5. **At least two materially different architectures**
6. **Trade-offs**
7. **Failure modes**
8. **What you would prototype first**
9. **What you would benchmark**
10. **What you would defer until the system proves valuable**

The goal is to determine whether the current:

> Evidence → Embeddings → Clustering → LLM Analysis

architecture is actually justified, or whether a simpler architecture would produce equal or better results.
