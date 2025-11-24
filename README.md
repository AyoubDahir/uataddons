# BizCore - UAT Addons

This repository contains custom Odoo addons for the BizCore system. These modules extend standard Odoo functionality to provide specialized business features.

## IDIL Module

The IDIL module provides inventory, accounting, and business management features tailored for specific industry needs.

### Key Features

- **Item Management**: Create and track inventory items with detailed properties
- **GL Account Integration**: Link items with accounting general ledger accounts
- **Chart of Accounts**: Custom chart of accounts implementation
- **Transaction Management**: Track financial transactions and movements
- **Currency Support**: Multi-currency support for all transactions

### Item Registration

The item registration feature allows users to create and manage inventory items with associated GL accounts:

- Each item can be linked to Purchase, Sales, Asset, and Adjustment accounts
- The system automatically suggests accounts based on item type and currency
- Domain filters ensure only compatible accounts are shown in dropdown lists

#### Currency-based Account Selection

When creating a new item:
1. First select the currency
2. The system will filter available GL accounts based on the selected currency
3. If similar items exist, the system will suggest accounts from those items

#### Troubleshooting Account Selection

If GL accounts aren't appearing in dropdowns:
1. Ensure you've selected a currency first
2. Use the "Check Available Accounts" button to verify available accounts
3. Verify that GL accounts exist with the correct header types and currency

## Installation

1. Clone this repository to your Odoo addons directory:
```
git clone https://github.com/username/uataddons.git
```

2. Update your Odoo configuration file to include this directory in the addons path:
```
addons_path = /path/to/odoo/addons,/path/to/uataddons
```

3. Restart your Odoo server
4. Install the required modules from the Apps menu

## Configuration

After installation:

1. Configure your chart of accounts
2. Set up default accounts for different item types
3. Configure currencies if using multiple currencies

## Development

When developing new features:

1. Follow Odoo development guidelines
2. Use the existing model structure and inheritance patterns
3. Test extensively with different currencies and account configurations

## Support

For issues or questions, contact the support team at support@example.com.
