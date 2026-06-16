# Sample Test Data

Use these IDs consistently across Postman, integration tests, and manual testing.

## Contributors

| entity_id | document_type | filename              | Notes                    |
|-----------|---------------|----------------------|--------------------------|
| U001      | identity      | passport.pdf         | Standard identity doc    |
| U001      | identity      | national_id.jpg      | Image document           |
| U002      | contracts     | contribution_agreement.pdf | Contract doc        |
| U003      | bank_details  | bank_statement.pdf   | Financial document       |

## Beneficiaries

| entity_id | document_type | filename              | Notes                    |
|-----------|---------------|----------------------|--------------------------|
| B001      | claims        | claim_form.pdf       | Claim document           |
| B001      | identity      | birth_certificate.pdf| Identity proof           |
| B002      | medical       | medical_report.pdf   | Medical evidence         |

## Employees

| entity_id | document_type | filename              | Notes                    |
|-----------|---------------|----------------------|--------------------------|
| E001      | contracts     | offer_letter.docx    | Word document            |
| E001      | contracts     | employment_contract.pdf | PDF contract          |
| E042      | payroll       | payslip_jan_2024.pdf | Payroll document         |

## Object Naming Convention

```
{entity_type}/{entity_id}/{document_type}/{filename}

Examples:
contributors/U001/identity/passport.pdf
beneficiaries/B001/claims/claim_form.pdf
employees/E001/contracts/offer_letter.docx
temp/UPLOAD_SESSION_123/upload/large_file.zip
```

## MinIO Bucket Map

| Bucket               | entity_type    |
|----------------------|----------------|
| dms-contributors     | contributors   |
| dms-beneficiaries    | beneficiaries  |
| dms-employees        | employees      |
| dms-temp             | temp           |

## Postman Variables

Set these as Collection Variables in Postman:

```
base_url      = http://localhost:8000/api/v1
entity_type   = contributors
entity_id     = U001
document_type = identity
filename      = passport.pdf
```
