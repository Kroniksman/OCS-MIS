"""
What the extractor reads from Coal Washery, and how each table is scoped.

**This file is the only place that knows CW's schema.** Everything downstream
reads the extractor's own store, so when CW moves, this is what changes — one
file, with a test that fails the moment it drifts.

Two rules, both learned from CW itself:

**Columns are allow-listed, never deny-listed.** A deny-list fails silently in
the future: the next migration that adds a secret column exports it and nobody
finds out. `users.password_hash` and `users.session_token` are excluded here by
name, and `check_drift()` fails the build when any table gains a column this
file does not declare — which turns "somebody forgot" into a red test.

**Scope is two-shaped.** CW scopes rows by `site_id` *and* `group_id`, and some
rows legitimately carry a NULL `site_id` — a mobile diesel tanker belongs to a
company and to no single washery. Filtering on `site_id` alone silently drops
every shared master. CW spent three releases on this distinction (1.7.1-1.7.3,
the last correcting the middle one); the extractor meets the same shape with
nothing above it to catch the mistake, so it is declared per table rather than
inferred per query.

  global                 no tenant column - platform-wide reference data
  site                   scoped by site_id alone
  group_or_site          company-wide; use group_id, fall back to site_id
  parent:<table>.<fk>    a child row; its company is its parent's
"""

# Generated once from a live schema, then maintained by hand. Regenerating it
# wholesale would defeat check_drift(), which exists to make a change visible.
TABLES = {
    "site_groups": {
        "scope": "global",
        "columns": [
            "id", "name", "legal_name", "pan", "address", "contact", "logo",
            "subscription_status", "plan", "expires_at", "trial_ends_at", "max_users",
            "billing_notes"
        ],
    },
    "sites": {
        "scope": "global",
        "columns": [
            "id", "name", "address", "address2", "district", "pincode", "state", "active",
            "logo", "group_id", "subscription_status", "plan", "expires_at",
            "trial_ends_at", "max_users", "billing_notes"
        ],
    },
    "users": {
        "scope": "site",
        # withheld deliberately: password_hash, session_token
        "columns": [
            "id", "site_id", "name", "email", "role_id", "active", "is_superadmin",
            "company_id", "is_company_admin", "is_owner", "created_at",
            "failed_login_attempts", "locked_until"
        ],
    },
    "roles": {
        "scope": "global",
        "columns": [
            "id", "name"
        ],
    },
    "debtors": {
        "scope": "group_or_site",
        "columns": [
            "id", "site_id", "group_id", "name", "party_type", "address", "place",
            "pincode", "gstn", "mobile", "email", "active", "created_at", "credit_days",
            "state_code", "tcs_exempt", "form_27c_ref"
        ],
    },
    "creditors": {
        "scope": "group_or_site",
        "columns": [
            "id", "site_id", "group_id", "name", "party_type", "is_transporter", "address",
            "place", "gstn", "mobile", "email", "active", "created_at", "state_code",
            "transin"
        ],
    },
    "vehicles": {
        "scope": "group_or_site",
        "columns": [
            "id", "site_id", "group_id", "vehicle_no", "vehicle_type", "transporter_id",
            "capacity_mt", "permit_no", "active"
        ],
    },
    "coal_sources": {
        "scope": "site",
        "columns": [
            "id", "site_id", "name", "source_type", "colliery", "subsidiary",
            "grade_declared", "creditor_id", "notes", "active", "created_at"
        ],
    },
    "stock_items": {
        "scope": "global",
        "columns": [
            "id", "name", "material_type", "unit", "hsn_code", "gst_rate", "active"
        ],
    },
    "stock_sizes": {
        # Its parent is global, so it is global too. Declaring it parent-scoped
        # was a modelling slip: it resolved every row's company to None and the
        # attribution test caught all 31 of them.
        "scope": "global",
        "columns": [
            "id", "stock_item_id", "size_grade", "description", "active"
        ],
    },
    "material_rates": {
        "scope": "group_or_site",
        "columns": [
            "id", "site_id", "group_id", "stock_item_id", "creditor_id", "source_place",
            "effective_date", "rate", "created_at"
        ],
    },
    "transport_rates": {
        "scope": "group_or_site",
        "columns": [
            "id", "site_id", "group_id", "transporter_id", "source", "destination",
            "route", "effective_date", "rate", "created_at"
        ],
    },
    "company_assets": {
        "scope": "site",
        "columns": [
            "id", "site_id", "asset_type", "name", "make", "vendor_name", "purchase_date",
            "chassis_no", "engine_no", "capacity", "insurance_date", "fitness_date",
            "model_no", "serial_no", "remarks", "active", "created_at"
        ],
    },
    "gates": {
        "scope": "site",
        "columns": [
            "id", "site_id", "name", "code", "location", "active", "created_at"
        ],
    },
    "gate_entries": {
        "scope": "site",
        "columns": [
            "id", "site_id", "gate_id", "crn", "sno", "entry_at", "status", "vehicle_no",
            "vehicle_id", "driver_name", "driver_mobile", "transporter_id",
            "transporter_name", "ownership", "creditor_id", "owner_debtor_id",
            "coal_source_id", "challan_no", "challan_mt", "transit_pass_no", "remarks",
            "weighment_id", "created_by", "created_at", "declared_grade_code", "lot_id",
            "eway_bill_no", "do_id"
        ],
    },
    "weighments": {
        "scope": "site",
        "columns": [
            "id", "site_id", "sno", "type", "party_type", "status", "vehicle_id",
            "transporter_id", "stock_item_id", "lp_no", "remarks", "debtor_id",
            "destination", "po_id", "po_line_id", "po_rate", "material_rate",
            "transport_rate", "royalty_no", "royalty_rate", "outward_type",
            "rake_indent_id", "creditor_id", "source_place", "inward_material_rate",
            "deduction_mt", "weight_1", "weight_2", "gross", "tare", "net_weight",
            "manual_w1", "manual_w2", "captured_by_1", "captured_at_1", "captured_by_2",
            "captured_at_2", "cancelled_by", "cancelled_at", "cancel_reason",
            "finalized_dispatch_id", "finalized_inward_id", "ownership", "owner_debtor_id",
            "coal_source_id", "gate_entry_id", "do_id", "token_id"
        ],
    },
    "rom_inward": {
        "scope": "site",
        "columns": [
            "id", "site_id", "txn_id", "sno", "date", "party_type", "ownership",
            "owner_debtor_id", "coal_source_id", "vehicle_id", "transporter_id",
            "creditor_id", "weighment_id", "lp_no", "rst_no", "gross_mt", "tare_mt",
            "net_mt", "challan_no", "do_no", "transit_pass_no", "tp_valid_upto",
            "eway_bill_no", "stock_item_id", "stock_size_id", "material_rate",
            "transport_rate", "deduction_mt", "deduction_amount", "material_amount",
            "transport_amount", "royalty_amount", "dmf_amount", "nmet_amount",
            "cess_amount", "quality_sample_id", "status", "remarks", "created_by",
            "created_at", "lot_id", "do_id", "po_id"
        ],
    },
    "wash_batches": {
        "scope": "site",
        "columns": [
            "id", "site_id", "txn_id", "sno", "date", "shift", "plant_id", "ownership",
            "owner_debtor_id", "rom_stock_item_id", "rom_stock_size_id", "rom_input_mt",
            "total_output_mt", "loss_mt", "operating_hours", "downtime_hours",
            "power_units_kwh", "magnetite_consumed_mt", "flocculant_kg", "water_kl",
            "remarks", "created_by", "created_at", "lot_id"
        ],
    },
    "wash_batch_outputs": {
        "scope": "parent:wash_batches.wash_batch_id",
        "columns": [
            "id", "wash_batch_id", "line_no", "output_class", "stock_item_id",
            "stock_size_id", "output_qty_mt", "pct_of_input", "quality_sample_id"
        ],
    },
    "quality_samples": {
        "scope": "site",
        "columns": [
            "id", "site_id", "sample_no", "date", "ref_type", "ref_id", "collected_by",
            "collected_at", "lab", "lab_name", "status", "remarks", "created_by",
            "created_at", "stage", "qc_ok", "qc_note"
        ],
    },
    "quality_results": {
        "scope": "parent:quality_samples.quality_sample_id",
        "columns": [
            "id", "quality_sample_id", "parameter", "value", "uom", "basis", "tested_at",
            "tested_by", "method", "created_at", "source"
        ],
    },
    "outward_dispatch": {
        "scope": "site",
        "columns": [
            "id", "site_id", "txn_id", "sno", "date", "party_type", "lp_no", "rst_no",
            "vehicle_id", "weight_mt", "transporter_id", "debtor_id", "destination",
            "stock_item_id", "stock_size_id", "transport_rate", "po_id", "po_line_id",
            "po_rate", "outward_type", "rake_indent_id", "royalty_no", "royalty_weight_mt",
            "royalty_rate", "royalty_amount", "transport_amount", "material_amount",
            "challan_no", "created_by", "created_at", "ownership", "owner_debtor_id",
            "eway_bill_no", "declared_grade_code", "declared_gcv", "lot_id"
        ],
    },
    "stock_movements": {
        "scope": "site",
        "columns": [
            "id", "site_id", "date", "stock_item_id", "stock_size_id", "ownership",
            "owner_debtor_id", "stockpile_id", "movement_type", "ref_type", "ref_id",
            "qty_mt", "reason", "approved_by", "approved_at", "created_by", "created_at"
        ],
    },
    "sales_invoices": {
        "scope": "site",
        "columns": [
            "id", "site_id", "invoice_no", "date", "debtor_id", "bill_to_name",
            "bill_to_gstin", "bill_to_address", "bill_to_state_code", "ship_to_name",
            "ship_to_address", "ship_to_place", "ship_to_pincode", "ship_to_state_code",
            "place_of_supply", "interstate", "taxable_amount", "cgst_rate", "sgst_rate",
            "igst_rate", "cgst_amount", "sgst_amount", "igst_amount", "cess_amount",
            "tcs_rate", "tcs_amount", "tcs_exempt", "tcs_exempt_ref", "round_off",
            "total_amount", "status", "issued_at", "cancelled_at", "cancel_reason",
            "remarks", "created_by", "created_at"
        ],
    },
    "sales_invoice_lines": {
        "scope": "parent:sales_invoices.invoice_id",
        "columns": [
            "id", "invoice_id", "line_no", "dispatch_id", "description", "hsn_code",
            "challan_no", "dispatch_date", "vehicle_no", "quantity_mt", "rate", "amount",
            "gst_rate"
        ],
    },
    "eway_bills": {
        "scope": "site",
        "columns": [
            "id", "site_id", "ewb_no", "direction", "status", "doc_date", "ref_type",
            "ref_id", "ref_no", "vehicle_no", "from_place", "to_place", "distance_km",
            "value_amount", "generated_at", "valid_upto", "cancelled_at", "cancel_reason",
            "gsp_ref", "remarks", "created_by", "created_at", "provider", "doc_type",
            "doc_no", "supply_type", "sub_supply_type", "sub_supply_desc",
            "transaction_type", "from_gstin", "from_trd_name", "from_addr", "from_pincode",
            "from_state_code", "to_gstin", "to_trd_name", "to_addr", "to_pincode",
            "to_state_code", "hsn_code", "product_name", "product_desc", "quantity",
            "qty_unit", "taxable_value", "cgst_rate", "sgst_rate", "igst_rate",
            "cess_rate", "cgst_amount", "sgst_amount", "igst_amount", "cess_amount",
            "cess_nonadvol_amount", "other_value", "trans_mode", "vehicle_type",
            "transporter_id", "transporter_name", "trans_doc_no", "trans_doc_date",
            "cancel_reason_code", "payload", "response", "extended_count", "part_b_count",
            "act_to_state_code"
        ],
    },
    "transit_passes": {
        "scope": "site",
        "columns": [
            "id", "site_id", "tp_no", "issued_on", "valid_upto", "quantity_mt",
            "balance_mt", "source_ref", "coal_source_id", "issuing_authority", "status",
            "remarks", "created_by", "created_at", "source_kind"
        ],
    },
    "audit_logs": {
        "scope": "site",
        "columns": [
            "id", "user_id", "user_name", "user_email", "site_id", "action", "entity_type",
            "entity_id", "description", "ip_address", "timestamp"
        ],
    },
}


#: Tables that may legitimately hold rows belonging to no company.
#:
#: The platform superadmin has no site and no company, and their actions are
#: recorded the same way. An unattributed row in these two is correct; anywhere
#: else it means the scoping rule for that table is wrong, which is how the
#: stock_sizes slip above was found.
PLATFORM_ROWS = ("users", "audit_logs")


#: Columns that must never leave CW, whatever a future migration calls them.
#: Belt and braces on top of the allow-list above — `check_drift` refuses to
#: run if one of these ever appears in a declared column list.
NEVER_EXPORT = ("password_hash", "session_token", "secret", "api_key", "private_key")


def check_drift(live_columns):
    """
    Compare the declared contract against a live CW schema.

    `live_columns` is {table: [column, ...]}. Returns a list of human-readable
    findings; empty means the contract still describes reality.

    A new column is a finding, not a warning. It is the case that leaks: the
    extractor would either miss data it should carry, or carry something nobody
    reviewed.
    """
    findings = []

    for table, spec in TABLES.items():
        for col in spec["columns"]:
            if any(bad in col.lower() for bad in NEVER_EXPORT):
                findings.append(
                    f"{table}.{col} is declared for export but matches NEVER_EXPORT")

        live = live_columns.get(table)
        if live is None:
            findings.append(f"{table}: declared in the contract, absent from CW")
            continue

        declared = set(spec["columns"])
        withheld = set(_withheld(table))
        added = set(live) - declared - withheld
        gone = declared - set(live)

        for col in sorted(added):
            findings.append(f"{table}.{col} is new in CW and not declared here")
        for col in sorted(gone):
            findings.append(f"{table}.{col} is declared here but gone from CW")

    return findings


def _withheld(table):
    """Columns deliberately not exported — parsed from the comment above them."""
    return _WITHHELD.get(table, ())


_WITHHELD = {
    "users": ('password_hash', 'session_token'),
}
