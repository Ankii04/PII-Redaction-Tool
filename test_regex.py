import re

text1 = 'Our Company was originally incorporated as “Bhandary Metal Extrusion Private Limited” under the provisions of the Companies Act, 1956'
text2 = 'Contact Person: Sarthak Malvadkar, Company Secretary and Compliance Officer; Telephone: + 91 20 4505 3237;'
text3 = 'The Promoters are Kushal Subbayya Hegde, Pushpa Kushal Hegde, Rajesh Kushal Hegde, Rohit Kushal Hegde, Rakhi Girija Shetty, Dhaulagiri Family Trust and Waterloo Industrial Park VI Private Limited'
text4 = 'Audited by Deloitte Haskins & Sells LLP and BSR & Co. LLP'
text5 = 'Mr. Rajesh Kumar was appointed as Managing Director: Priya Singh and CFO: Arjun Mehta'

# 1. Company regex
company_pat = re.compile(
    r'(?:[\u2018\u2019\u201c\u201d\"\'\(]?\b[A-Z][A-Za-z0-9\'-]*(?:\s+(?:&|[A-Z0-9][A-Za-z0-9\'-]*)){0,8}'
    r'\s+(?:Private\s+Limited|Pvt\.?\s*Ltd\.?|Public\s+Limited|Limited|LLP|Corporation|Corp\.?|Incorporated|Inc\.?|Holdings|Securities|Technologies|Solutions|Services|Infrastructure|Industries|Enterprises|Investments|Finance)\b[\u2018\u2019\u201c\u201d\"\'\)]?)'
)

# 2. Context Person regex
person_pat = re.compile(
    r'(?:(?:Contact\s+Person|Director|Promoter|Secretary|Officer|Auditor|Executive|Manager|Partner|CFO|CEO|MD|CMD|Name)\s*[:\-]\s*|(?:Mr\.|Ms\.|Mrs\.|Dr\.|Shri|Smt\.?)\s+)'
    r'([A-Z][a-z]+(?:\s+[A-Z][a-z]+){1,4})'
)

print('--- Test 1 (Company):', text1)
for m in company_pat.finditer(text1):
    print('  Found company:', repr(m.group()))

print('\n--- Test 2 (Person):', text2)
for m in person_pat.finditer(text2):
    print('  Found person:', repr(m.group(1)))

print('\n--- Test 3 (Promoters):', text3)
for m in company_pat.finditer(text3):
    print('  Found company:', repr(m.group()))

print('\n--- Test 4 (Auditors):', text4)
for m in company_pat.finditer(text4):
    print('  Found company:', repr(m.group()))

print('\n--- Test 5 (Context Person):', text5)
for m in person_pat.finditer(text5):
    print('  Found person:', repr(m.group(1)))
