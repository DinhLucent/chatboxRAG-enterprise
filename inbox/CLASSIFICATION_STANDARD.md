# Document Classification Standard For AI Agent

This file is the intake rulebook. When many documents are placed in `inbox/`, the AI agent must classify, draft metadata, and prepare files according to this standard before running ingestion.

## Goal

The document owner only provides files. The AI agent handles:

1. Detect document type.
2. Place or keep the file in the correct inbox category.
3. Draft sidecar metadata when missing.
4. Run the intake pipeline.
5. Stop at `pending_review`; never approve automatically.

## Allowed Taxonomy

```text
company
└── department
    └── technical
        ├── procedure
        ├── vendor_document
        ├── form_checklist
        └── faq_troubleshooting
```

## Category Rules

### procedure

Use for internal company or department procedures.

Signals:

- SOP, process, policy, work instruction, internal rule.
- Has steps, roles, responsibilities, approval, effective date, or version.
- Describes how the technical team must do a repeated workflow.

Examples:

- Incident handling procedure.
- Commissioning procedure.
- Periodic maintenance procedure.
- Equipment handover procedure.

### vendor_document

Use for documents from manufacturers, partners, vendors, or product suppliers.

Signals:

- Manual, datasheet, catalog, installation guide, maintenance guide.
- Has brand, model, product code, specification table, wiring, device setup, or vendor troubleshooting.
- Mostly describes a product or device rather than an internal company process.

Examples:

- Product manual.
- Datasheet.
- Catalog.
- Vendor troubleshooting guide.

### form_checklist

Use for forms, templates, checklists, reports, or documents that people fill in.

Signals:

- Blank fields, signature area, pass/fail table, check boxes, inspection list.
- Used as evidence, report, checklist, or handover record.

Examples:

- Acceptance record.
- Inspection checklist.
- Incident report form.
- Technical service report template.

### faq_troubleshooting

Use for confirmed FAQs, known issues, fault codes, lessons learned, or short repair instructions.

Signals:

- Question and answer structure.
- Error code, symptom, root cause, fix, test method, workaround.
- Internal troubleshooting knowledge confirmed by the technical team.

Examples:

- Error E-07 resolution.
- Device cannot connect FAQ.
- Common fault code table.
- Confirmed incident handling notes.

## Quick Decision Rules

```text
Internal steps or policy        -> procedure
Vendor/product/device material  -> vendor_document
Fillable/checkable template     -> form_checklist
Error/fault/fix knowledge       -> faq_troubleshooting
```

If uncertain:

1. Prefer the folder name if the user already placed the file under a category folder.
2. Prefer sidecar metadata if `*.metadata.json` exists and is valid.
3. Use filename and first readable content to infer category.
4. Keep low-confidence items in queue and mention the uncertainty in `status_reason`.

## Required Metadata

Every prepared document must have:

```json
{
  "doc_id": "KT-QT-001",
  "title": "Document title",
  "department": "technical",
  "category": "procedure",
  "source_type": "internal_procedure",
  "language": "vi",
  "version": "1.0",
  "effective_from": "2026-01-01",
  "review_at": "2026-12-31",
  "owner": "Phong Ky thuat",
  "access_group": "technical"
}
```

## Doc ID Prefixes

```text
procedure            -> KT-QT-###
vendor_document      -> KT-HANG-###
form_checklist       -> KT-BM-###
faq_troubleshooting  -> KT-FAQ-###
```

## Agent Workflow

```text
inbox/
-> classify using this file
-> create or validate sidecar metadata
-> prepare-inbox
-> process-source with MinerU when needed
-> create manifest record status=pending_review
-> wait for human review
```

The agent must not move a document to `active`. Only a reviewer can approve it.

## Output Expectations

After processing, the dashboard should show:

- `Queue`: files still waiting in inbox, pending review, or failed review.
- `Processed`: documents already in governed manifest or recent successful ingestion runs.
- `Review`: documents requiring human approval before chatbot use.
