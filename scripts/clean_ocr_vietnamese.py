import json
import re
import sys
from pathlib import Path

# Ensure UTF-8 output encoding
sys.stdout.reconfigure(encoding='utf-8')
sys.stderr.reconfigure(encoding='utf-8')

root = Path(__file__).resolve().parent.parent
records_path = root / "manifest" / "records.json"

if not records_path.exists():
    print(f"Error: records.json not found at {records_path}")
    sys.exit(1)

data = json.loads(records_path.read_text(encoding="utf-8"))
active_records = [r for r in data if r["status"] == "active"]

# Dictionary of replacement patterns (regex pattern, replacement string)
# Capitalization variations are handled separately to preserve visual format
REPLACEMENTS = [
    # Lắp đặt
    (r"l[áa]p\s+d[ǎăä]t", "lắp đặt"),
    (r"L[áa]p\s+d[ǎăä]t", "Lắp đặt"),
    (r"l[áa]p\s+d[áa]t", "lắp đặt"),
    (r"L[áa]p\s+d[áa]t", "Lắp đặt"),
    
    # Thực hiện
    (r"Thurc\s+hi[èeê]n", "Thực hiện"),
    (r"thurc\s+hi[èeê]n", "thực hiện"),
    (r"th[uư]rc\s+hi[ēeê]", "thực hiện"),
    (r"Th[uư]rc\s+hi[ēeê]", "Thực hiện"),
    (r"thurchi[ēeê]n", "thực hiện"),
    (r"Thurchi[ēeê]n", "Thực hiện"),
    (r"Thực\s+hi[èeê]n", "Thực hiện"),
    (r"thực\s+hi[èeê]n", "thực hiện"),
    (r"thrc\s+hi[ēeê]", "thực hiện"),
    (r"Thrc\s+hi[ēeê]", "Thực hiện"),
    (r"thrc\s+hi[èeê]", "thực hiện"),
    (r"Thrc\s+hi[èeê]", "Thực hiện"),
    (r"Thurc\b", "Thực"),
    (r"thurc\b", "thực"),
    (r"thrc\b", "thực"),
    
    # Hồ sơ
    (r"h[òo]\s+so\b", "hồ sơ"),
    (r"H[òo]\s+so\b", "Hồ sơ"),
    (r"h[òo]\s+sơ\b", "hồ sơ"),
    (r"H[òo]\s+sơ\b", "Hồ sơ"),
    
    # Điều kiện
    (r"di[èe]u\s+ki[èeê]n", "điều kiện"),
    (r"Di[èe]u\s+ki[èeê]n", "Điều kiện"),
    (r"dieu\s+kien", "điều kiện"),
    (r"Dieu\s+kien", "Điều kiện"),
    (r"dièu\s+ki[ēeê]", "điều kiện"),
    (r"Dièu\s+ki[ēeê]", "Điều kiện"),
    
    # Công việc
    (r"c[òo]ng\s+vi[èeê]c", "công việc"),
    (r"C[òo]ng\s+vi[èeê]c", "Công việc"),
    (r"cong\s+viec", "công việc"),
    (r"Cong\s+viec", "Công việc"),
    
    # Dịch vụ kỹ thuật
    (r"d[iị]ch\s+v[uụ]\s+k[yỹ]\s+thu[aậ]t", "dịch vụ kỹ thuật"),
    (r"D[iị]ch\s+v[uụ]\s+k[yỹ]\s+thu[aậ]t", "Dịch vụ kỹ thuật"),
    (r"dich\s+vu\s+ky\s+thuat", "dịch vụ kỹ thuật"),
    (r"Dich\s+vu\s+ky\s+thuat", "Dịch vụ kỹ thuật"),
    (r"dich\s+vu\b", "dịch vụ"),
    (r"Dich\s+vu\b", "Dịch vụ"),
    (r"ky\s+thuat\b", "kỹ thuật"),
    (r"Ky\s+thuat\b", "Kỹ thuật"),
    (r"ky\s+s[uư]r\b", "kỹ sư"),
    (r"Ky\s+s[uư]r\b", "Kỹ sư"),
    
    # Quy trình / quy định
    (r"quy\s+tr[iì]nh\b", "quy trình"),
    (r"Quy\s+tr[iì]nh\b", "Quy trình"),
    (r"QUY\s+TR[iì]NH\b", "QUY TRÌNH"),
    (r"quy\s+tr[iì]nh\s+n[aà]y", "quy trình này"),
    (r"quy\s+tr[iì]nh\s+nay", "quy trình này"),
    
    # Tài liệu
    (r"t[aà]i\s+li[èe]u\b", "tài liệu"),
    (r"T[aà]i\s+li[èe]u\b", "Tài liệu"),
    (r"t[aà]i\s+lieu\b", "tài liệu"),
    (r"T[aà]i\s+lieu\b", "Tài liệu"),
    (r"M[aāà]\s+t[aà]i\s+li[èe]u\b", "Mã tài liệu"),
    (r"M[aāà]\s+t[aà]i\s+lieu\b", "Mã tài liệu"),
    (r"Ma\s+t[aà]i\s+i[éé]u\b", "Mã tài liệu"),
    (r"Ma\s+s[óo]\s+t[aà]i\s+li[èe]u\b", "Mã số tài liệu"),
    
    # Phiên bản
    (r"Phi[èeê]n\s+b[ǎaà]n", "Phiên bản"),
    (r"phi[èeê]n\s+b[ǎaà]n", "phiên bản"),
    (r"Phi[èeê]n\s+b[aà]in", "Phiên bản"),
    (r"Phi[èeê]n\s+ban", "Phiên bản"),
    (r"Phien\s+ban", "Phiên bản"),
    (r"Phi[eê]n\s+b[ǎaà]n", "Phiên bản"),
    
    # Người
    (r"ngr[uò]i", "người"),
    (r"ngur[òo]i", "người"),
    (r"Ngu[òo]i", "Người"),
    (r"Ngr[òo]i", "Người"),
    (r"ngw[òo]i", "người"),
    (r"ngui\b", "người"),
    
    # Gửi / nhận
    (r"giri\b", "gửi"),
    (r"Giri\b", "Gửi"),
    (r"girri\b", "gửi"),
    (r"nhan\b", "nhận"),
    (r"Nhan\b", "Nhận"),
    (r"thur\b", "thư"),
    (r"Thur\b", "Thư"),
    (r"chuyn\b", "chuyển"),
    (r"Chuyn\b", "Chuyển"),
    (r"chuyn\s+ph[aá]t", "chuyển phát"),
    (r"Chuyn\s+ph[aá]t", "Chuyển phát"),
    
    # Biểu mẫu
    (r"Bi[ěeê]u\s+m[ǎaà]u\b", "Biểu mẫu"),
    (r"bi[ěeê]u\s+m[ǎaà]u\b", "biểu mẫu"),
    (r"Bi[eê]u\s+m[ǎaà]u\b", "Biểu mẫu"),
    (r"Bium[ǎaà]u\b", "Biểu mẫu"),
    (r"Bi[èe]u\s+m[aãà]u\b", "Biểu mẫu"),
    (r"Bi[èe]u\s+m[uụ]\b", "Biểu mẫu"),
    
    # Khác
    (r"ch[ǎa]m\s+s[óo]c\b", "chăm sóc"),
    (r"Ch[ǎa]m\s+s[óo]c\b", "Chăm sóc"),
    (r"d[èe]n\s+b[ùu]\b", "đền bù"),
    (r"D[èe]n\s+b[ùu]\b", "Đền bù"),
    (r"v[ǎa]n\s+ph[òo]ng\b", "văn phòng"),
    (r"V[ǎa]n\s+ph[òo]ng\b", "Văn phòng"),
    (r"c[òo]ng\s+ty\b", "công ty"),
    (r"C[òo]ng\s+ty\b", "Công ty"),
    (r"cngty\b", "công ty"),
    (r"B[òo]\s+ph[àa]n\b", "Bộ phận"),
    (r"b[òo]\s+ph[àa]n\b", "bộ phận"),
    (r"Bo\s+phan\b", "Bộ phận"),
    (r"l[iì]n\s+quan", "liên quan"),
    (r"li[ēeê]\s+quan", "liên quan"),
    (r"Li[ēeê]\s+quan", "Liên quan"),
    (r"S[oơ]\s+d[òo]\b", "Sơ đồ"),
    (r"ch[iì]nh\s+s[iì]ra\b", "chỉnh sửa"),
    (r"ch[iì]nh\s+ira\b", "chỉnh sửa"),
    (r"s[iì]rad[óo]i\b", "sửa đổi"),
    (r"si[aà]\s+di\b", "sửa đổi"),
    (r"s[iì]ra\b", "sửa"),
    (r"S[iì]ra\b", "Sửa"),
    (r"l[aà]n\b", "lần"),
    (r"l[aà]n\s+d[aà]u", "lần đầu"),
    (r"d[aà]u\b", "đầu"),
    (r"d[aâ]u\b", "đầu"),
    (r"ng[aà]y\s+th[aà]ng\b", "ngày tháng"),
    (r"Ng[aà]y\s+th[aà]ng\b", "Ngày tháng"),
    (r"Ng[aà]y\s+thng\b", "Ngày tháng"),
    (r"trach\s+nhiem\b", "trách nhiệm"),
    (r"Trach\s+nhiem\b", "Trách nhiệm"),
    (r"Tr[aá]chnhiem\b", "Trách nhiệm"),
    (r"l[uư]ru\b", "lưu"),
    (r"L[uư]ru\b", "Lưu"),
    (r"l[uư]ru\s+tr[iị]", "lưu trữ"),
    (r"tr[iị]r\b", "trữ"),
    (r"th[òo]ng\s+tin\b", "thông tin"),
    (r"Th[òo]ng\s+tin\b", "Thông tin"),
    (r"thong\s+tin\b", "thông tin"),
    (r"kh[aá]ch\s+h[aà]ng\b", "khách hàng"),
    (r"Kh[aá]ch\s+h[aà]ng\b", "Khách hàng"),
    (r"khach\s+hang\b", "khách hàng"),
    (r"h[aá]ch\s+h[aà]ng\b", "khách hàng"),
    (r"hach\s+hang\b", "khách hàng"),
    (r"b[aà]o\s+qu[aà]n\b", "bảo quản"),
    (r"B[aà]o\s+qu[aà]n\b", "Bảo quản"),
    (r"bao\s+qun\b", "bảo quản"),
    (r"v[aà]n\s+chuyn\b", "vận chuyển"),
    (r"V[aà]n\s+chuyn\b", "Vận chuyển"),
    (r"van\s+chuyen\b", "vận chuyển"),
    (r"an\s+chuyn\b", "vận chuyển"),
    (r"hieu\s+lurc\b", "hiệu lực"),
    (r"hieu\s+lure\b", "hiệu lực"),
    (r"hi[èe]\s+lrc\b", "hiệu lực"),
    (r"hieu\s+lr\b", "hiệu lực"),
    (r"hiu\s+lr\b", "hiệu lực"),
]

# Compile regular expressions
compiled_replacements = []
for pattern, replacement in REPLACEMENTS:
    compiled_replacements.append((re.compile(pattern), replacement))

files_modified = 0
total_replacements = 0

for r in active_records:
    doc_id = r["doc_id"]
    version = r["version"]
    norm_path_str = r.get("normalized_path")
    
    if not norm_path_str:
        continue
        
    norm_path = Path(norm_path_str)
    if not norm_path.is_absolute():
        norm_path = root / norm_path
        
    if not norm_path.exists():
        continue
        
    text = norm_path.read_text(encoding="utf-8", errors="replace")
    
    # Split YAML frontmatter from Markdown body
    parts = text.split("---", 2)
    if len(parts) >= 3:
        frontmatter = parts[1]
        body = parts[2]
        prefix = f"---{frontmatter}---"
    else:
        # No frontmatter found, process whole file
        prefix = ""
        body = text
        
    original_body = body
    local_replacements = 0
    
    # Perform regex replacements in body
    for regex, replacement in compiled_replacements:
        body, count = regex.subn(replacement, body)
        local_replacements += count
        
    if local_replacements > 0:
        new_text = prefix + body
        norm_path.write_text(new_text, encoding="utf-8")
        files_modified += 1
        total_replacements += local_replacements
        print(f"[+] Cleaned {doc_id} {version}: {local_replacements} replacements made.")

print("\nVietnamese Spelling Cleanup Summary:")
print(f"Total files modified: {files_modified}")
print(f"Total replacements made: {total_replacements}")
