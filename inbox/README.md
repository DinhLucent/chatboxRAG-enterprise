# Inbox Tai Lieu Cho AI Agent

Day la khay nhan tai lieu thô. Nguoi dung chi can tha file vao day; AI agent/operator se xu ly cac buoc con lai.

## Nguyen Tac Bat Buoc

- Agent phai doc `CLASSIFICATION_STANDARD.md` truoc khi phan loai tai lieu.
- Chi tao metadata nhap, convert, validate va dua tai lieu vao `pending_review`.
- Khong tu approve tai lieu sang `active`.
- Khong sync vao RAGFlow production neu tai lieu chua duoc approve.
- Khong xoa file goc trong `inbox/` neu nguoi dung chua yeu cau.
- Neu khong chac category/version/doc_id, hay tao metadata nhap hop ly va de nguoi duyet sua trong buoc review.

## Phan Loai Thu Muc

Dat file vao 1 trong cac thu muc sau neu biet ro loai tai lieu:

```text
inbox/procedure/
inbox/vendor_document/
inbox/form_checklist/
inbox/faq_troubleshooting/
```

Neu nguoi dung tha file truc tiep vao `inbox/`, agent tu doan category tu ten file, duong dan va noi dung neu co the.

### `procedure`

Dung cho quy trinh noi bo cua cong ty/phong ban.

Vi du:

- Quy trinh xu ly su co ky thuat
- Quy trinh nghiem thu sau trien khai
- Quy trinh bao tri dinh ky
- Quy trinh ban giao thiet bi
- Quy trinh escalation loi nghiem trong

Dau hieu: co buoc thuc hien, vai tro/trach nhiem, nguoi duyet, hieu luc, version.

### `vendor_document`

Dung cho tai lieu tu hang/doi tac/nha san xuat.

Vi du:

- Manual
- Datasheet
- Catalogue
- Installation guide
- Maintenance guide
- Troubleshooting guide cua hang
- Thong so ky thuat thiet bi

Dau hieu: co logo hang, model, ma san pham, bang thong so, huong dan lap dat/van hanh theo thiet bi.

### `form_checklist`

Dung cho bieu mau, checklist, file can dien hoac dung de kiem tra.

Vi du:

- Bien ban nghiem thu
- Checklist kiem tra thiet bi
- Phieu xu ly su co
- Mau bao cao ky thuat
- Mau ban giao

Dau hieu: co o trong, bang tick, muc can dien, chu ky, trang thai dat/khong dat.

### `faq_troubleshooting`

Dung cho hoi dap, loi thuong gap, kinh nghiem xu ly da xac nhan.

Vi du:

- Cach xu ly loi E-07
- FAQ loi ket noi thiet bi
- Bang ma loi va huong xu ly
- Kinh nghiem xu ly su co noi bo

Dau hieu: noi dung xoay quanh loi, nguyen nhan, cach kiem tra, cach khac phuc.

## Quy Tac Nhanh

```text
Co quy dinh/buoc lam noi bo     -> procedure
Co tai lieu tu hang/thiet bi    -> vendor_document
Co mau dien/check/tick/ky       -> form_checklist
Co loi/cau hoi/cach xu ly nhanh -> faq_troubleshooting
```

## File Duoc Ho Tro

```text
.md, .txt, .pdf, .docx, .pptx, .xlsx, .png, .jpg, .jpeg
```

## Metadata Tuy Chon

Neu nguoi dung/agent biet metadata chinh xac, tao file sidecar cung ten:

```text
KT-QT-003_v1.2.pdf
KT-QT-003_v1.2.metadata.json
```

Mau metadata:

```json
{
  "doc_id": "KT-QT-003",
  "title": "Quy trinh xu ly su co ky thuat",
  "department": "technical",
  "category": "procedure",
  "source_type": "internal_procedure",
  "language": "vi",
  "version": "1.2",
  "effective_from": "2025-01-01",
  "review_at": "2025-12-31",
  "owner": "Phong Ky thuat",
  "access_group": "technical"
}
```

Neu khong co sidecar, lenh `prepare-inbox` se tao metadata nhap.

## Lenh Cho AI Agent

Preview truoc khi copy:

```powershell
.\scripts\agent-ingest-inbox.ps1 -DryRun
```

Xu ly that:

```powershell
.\scripts\agent-ingest-inbox.ps1
```

Lenh tren se:

```text
inbox/
-> tao metadata nhap
-> copy sang source/technical/<category>/
-> MinerU convert sang Markdown neu can
-> validate metadata + normalized output
-> tao manifest record status=pending_review
```

Sau do nguoi duyet moi approve:

```powershell
python -m poc_workflow approve <DOC_ID> <VERSION> --approved-by "Ten nguoi duyet"
```

## Ket Qua Mong Doi

Sau khi agent xu ly, tai lieu hop le phai nam o:

```text
source/technical/<category>/
normalized/technical/<category>/
manifest/records.json
```

Va trang thai trong manifest phai la:

```text
pending_review
```
