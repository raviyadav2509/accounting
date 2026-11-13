# Validation

Performed on 14 November 2026 (Sydney date):

- Parsed all four Terraform files and the example variable file using `python-hcl2`.
- Parsed both Python scripts using Python's AST parser.
- Ran the deployment packager against a representative application directory layout.
- Verified the ZIP has root-level application files and the Azure WSGI entry point.
- Verified `.env`, token JSON, SQLite database files and Python bytecode are excluded.
- Verified Gunicorn is added when missing, and an existing Gunicorn requirement is preserved.
- Executed the WSGI wrapper with a stub application to check data-directory creation and secure cookie settings.
- Checked configuration names and the callback route against the GitHub repository.
- Checked App Service attributes against AzureRM provider documentation and Python hosting behavior against Microsoft documentation.

Not performed:

- `terraform fmt -check`, `terraform init`, provider-schema `terraform validate`, or an Azure plan/apply. Terraform was unavailable and downloading its binary timed out. HCL parsing is syntax verification, not provider validation.
- Live application deployment, QuickBooks OAuth, OpenAI calls, Azure quota/capacity checks or a persistence test on Azure.
- Verification of the inaccessible Azure DevOps copy of the application.

Run the commands in README.md in your Azure environment before deployment. No Azure resources were created.
