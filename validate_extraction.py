"""
JSON Validator for Air Permit Data Extraction Schema

Uses jsonschema library to validate against schema file, with custom business logic validators.
"""

import json
from typing import Any, Dict, List, Tuple
from pathlib import Path

try:
    import jsonschema
    from jsonschema import Draft7Validator, validators
except ImportError:
    raise ImportError(
        "jsonschema library is required. Install with: pip install jsonschema"
    )


class PermitDataValidator:
    """Validator for air permit extraction data following the defined schema."""
    
    def __init__(self, schema_path: str = None):
        """
        Initialize validator with JSON schema.
        
        Args:
            schema_path: Path to JSON schema file. If None, looks for 'schema.json' in same directory.
        """
        self.errors: List[str] = []
        self.warnings: List[str] = []
        self.equipment_reference_nos: set = set()
        
        # Load schema
        if schema_path is None:
            schema_path = Path(__file__).parent / "schema.json"
        
        with open(schema_path, 'r', encoding='utf-8') as f:
            self.schema = json.load(f)
        
        # Create validator
        self.validator = Draft7Validator(self.schema)
    
    def validate(self, data: Dict[str, Any]) -> Tuple[bool, List[str], List[str]]:
        """
        Validate permit data against schema.
        
        Returns:
            Tuple of (is_valid, errors, warnings)
        """
        self.errors = []
        self.warnings = []
        self.equipment_reference_nos = set()
        
        # 1. Validate against JSON Schema
        schema_errors = list(self.validator.iter_errors(data))
        for error in schema_errors:
            # Create readable error message
            path = ".".join(str(p) for p in error.absolute_path) if error.absolute_path else "root"
            self.errors.append(f"{path}: {error.message}")
        
        # If schema validation failed completely, don't continue with business logic
        if not isinstance(data, dict):
            return False, self.errors, self.warnings
        
        # 2. Custom business logic validation
        self._collect_equipment_references(data.get("equipmentSummary", []))
        self._validate_custom_business_logic(data)
        
        is_valid = len(self.errors) == 0
        return is_valid, self.errors, self.warnings
    
    def _collect_equipment_references(self, equipment_list: List[Dict]):
        """Collect all equipment reference numbers for cross-referencing."""
        if not isinstance(equipment_list, list):
            return
        
        for equipment in equipment_list:
            if isinstance(equipment, dict):
                ref_nos = equipment.get("referenceNos")
                if isinstance(ref_nos, str):
                    self.equipment_reference_nos.add(ref_nos)
    
    def _validate_custom_business_logic(self, data: Dict):
        """Validate custom business rules not covered by JSON Schema."""
        
        # Validate equipment summary
        if "equipmentSummary" in data:
            self._validate_equipment_summary_logic(data["equipmentSummary"])
        
        # Validate operational limits
        if "operationalLimits" in data:
            self._validate_operational_limits_logic(data["operationalLimits"])
        
        # Validate emission limits
        if "emissionLimits" in data:
            self._validate_emission_limits_logic(data["emissionLimits"])
    
    def _validate_equipment_summary_logic(self, equipment_list: List[Dict]):
        """Custom validation for equipment summary."""
        if not isinstance(equipment_list, list):
            return
        
        for idx, equipment in enumerate(equipment_list):
            if not isinstance(equipment, dict):
                continue
            
            path = f"equipmentSummary[{idx}]"
            
            # Check for deprecated fields
            if "electricalCapacity_kW" in equipment:
                self.errors.append(
                    f"{path}.electricalCapacity_kW: Deprecated field. "
                    f"Use electricalCapacity_kW_perUnit and electricalCapacity_kW_total"
                )
            
            if "mechanicalCapacity_bhp" in equipment:
                self.errors.append(
                    f"{path}.mechanicalCapacity_bhp: Deprecated field. "
                    f"Use mechanicalCapacity_bhp_perUnit and mechanicalCapacity_bhp_total"
                )
            
            if "gasUsage_MMBTUhr" in equipment:
                self.errors.append(
                    f"{path}.gasUsage_MMBTUhr: Deprecated field. "
                    f"Use gasUsage_MMBTUhr_perUnit"
                )
            
            # Validate capacity fields shouldn't be 0 (should be null)
            self._check_zero_vs_null(equipment, "electricalCapacity_kW_perUnit", path)
            self._check_zero_vs_null(equipment, "electricalCapacity_kW_total", path)
            self._check_zero_vs_null(equipment, "mechanicalCapacity_bhp_perUnit", path)
            self._check_zero_vs_null(equipment, "mechanicalCapacity_bhp_total", path)
            self._check_zero_vs_null(equipment, "gasUsage_MMBTUhr_perUnit", path)
            
            # Validate capacity consistency
            self._validate_capacity_consistency(equipment, path)
            
            # Validate numberOfUnits is positive integer
            num_units = equipment.get("numberOfUnits")
            if isinstance(num_units, (int, float)) and not isinstance(num_units, bool):
                if num_units <= 0:
                    self.errors.append(f"{path}.numberOfUnits: Must be positive, got {num_units}")
                elif num_units != int(num_units):
                    self.warnings.append(f"{path}.numberOfUnits: Expected integer count, got {num_units}")
    
    def _check_zero_vs_null(self, obj: Dict, field: str, path: str):
        """Warn if a capacity field is 0 (should be null if not specified)."""
        value = obj.get(field)
        if value == 0 or value == 0.0:
            self.warnings.append(
                f"{path}.{field}: Value is 0 - ensure this is explicitly stated in the "
                f"source document (should be null if not mentioned)"
            )
    
    def _validate_capacity_consistency(self, equipment: Dict, path: str):
        """Validate that total capacity = per-unit capacity × numberOfUnits."""
        num_units = equipment.get("numberOfUnits")
        
        if not isinstance(num_units, (int, float)) or isinstance(num_units, bool):
            return
        
        # Check electrical capacity
        per_unit_kw = equipment.get("electricalCapacity_kW_perUnit")
        total_kw = equipment.get("electricalCapacity_kW_total")
        
        if (per_unit_kw is not None and total_kw is not None and 
            isinstance(per_unit_kw, (int, float)) and isinstance(total_kw, (int, float))):
            expected_total = per_unit_kw * num_units
            if abs(total_kw - expected_total) > 0.01:
                self.warnings.append(
                    f"{path}: Electrical capacity mismatch. "
                    f"Per-unit ({per_unit_kw} kW) × units ({num_units}) = {expected_total} kW, "
                    f"but total is {total_kw} kW"
                )
        
        # Check mechanical capacity
        per_unit_bhp = equipment.get("mechanicalCapacity_bhp_perUnit")
        total_bhp = equipment.get("mechanicalCapacity_bhp_total")
        
        if (per_unit_bhp is not None and total_bhp is not None and 
            isinstance(per_unit_bhp, (int, float)) and isinstance(total_bhp, (int, float))):
            expected_total = per_unit_bhp * num_units
            if abs(total_bhp - expected_total) > 0.01:
                self.warnings.append(
                    f"{path}: Mechanical capacity mismatch. "
                    f"Per-unit ({per_unit_bhp} bhp) × units ({num_units}) = {expected_total} bhp, "
                    f"but total is {total_bhp} bhp"
                )
    
    def _validate_operational_limits_logic(self, limits_list: List[Dict]):
        """Custom validation for operational limits."""
        if not isinstance(limits_list, list):
            return
        
        for idx, limit in enumerate(limits_list):
            if not isinstance(limit, dict):
                continue
            
            path = f"operationalLimits[{idx}]"
            category = limit.get("category")
            
            # Validate cross-references
            applies_to = limit.get("appliesTo", [])
            if isinstance(applies_to, list):
                for ref_idx, ref_no in enumerate(applies_to):
                    if isinstance(ref_no, str) and ref_no:
                        if ref_no not in self.equipment_reference_nos:
                            self.warnings.append(
                                f"{path}.appliesTo[{ref_idx}]: Reference '{ref_no}' not found in "
                                f"equipmentSummary reference numbers. Check for exact match "
                                f"(spaces, dashes, capitalization)."
                            )
            
            # Validate structuredData
            structured_data = limit.get("structuredData")
            if structured_data is not None and isinstance(structured_data, dict):
                if category == "Hours of Operation Limits":
                    self._validate_hours_structured_data(structured_data, path)
                elif category == "Fuel Limits & Specifications":
                    self._validate_fuel_structured_data(structured_data, path)
                elif structured_data:
                    # Warn if structuredData exists for other categories
                    self.warnings.append(
                        f"{path}.structuredData: Populated for category '{category}', "
                        f"but structured fields are only defined for 'Hours of Operation Limits' "
                        f"and 'Fuel Limits & Specifications'"
                    )
    
    def _validate_hours_structured_data(self, data: Dict, path: str):
        """Validate structuredData for Hours of Operation Limits."""
        hour_limit = data.get("hourLimitPerUnit")
        if isinstance(hour_limit, (int, float)) and not isinstance(hour_limit, bool):
            if hour_limit < 0:
                self.errors.append(f"{path}.structuredData.hourLimitPerUnit: Cannot be negative")
            elif hour_limit > 8760:
                self.warnings.append(
                    f"{path}.structuredData.hourLimitPerUnit: "
                    f"Value {hour_limit} exceeds hours in a year (8760)"
                )
        
        combined_limit = data.get("hourLimitCombined")
        if isinstance(combined_limit, (int, float)) and not isinstance(combined_limit, bool):
            if combined_limit < 0:
                self.errors.append(f"{path}.structuredData.hourLimitCombined: Cannot be negative")
        
        # Check for unexpected fields
        valid_fields = {"calculationMethod", "hourLimitPerUnit", "hourLimitCombined"}
        for field in data.keys():
            if field not in valid_fields:
                self.warnings.append(
                    f"{path}.structuredData.{field}: Unexpected field for 'Hours of Operation Limits'. "
                    f"Valid fields are: {sorted(valid_fields)}"
                )
    
    def _validate_fuel_structured_data(self, data: Dict, path: str):
        """Validate structuredData for Fuel Limits & Specifications."""
        sulfur = data.get("maxSulfurContent_percent")
        if isinstance(sulfur, (int, float)) and not isinstance(sulfur, bool):
            if sulfur < 0:
                self.errors.append(f"{path}.structuredData.maxSulfurContent_percent: Cannot be negative")
            elif sulfur > 100:
                self.errors.append(
                    f"{path}.structuredData.maxSulfurContent_percent: "
                    f"Cannot exceed 100% (got {sulfur})"
                )
            elif sulfur > 5:
                self.warnings.append(
                    f"{path}.structuredData.maxSulfurContent_percent: "
                    f"Value {sulfur}% seems unusually high. Typical values are < 0.5%"
                )
        
        throughput = data.get("fuelThroughputLimit_gallons")
        if isinstance(throughput, (int, float)) and not isinstance(throughput, bool):
            if throughput < 0:
                self.errors.append(f"{path}.structuredData.fuelThroughputLimit_gallons: Cannot be negative")
        
        # Check for unexpected fields
        valid_fields = {
            "astmSpecification", 
            "maxSulfurContent_percent", 
            "fuelThroughputLimit_gallons", 
            "certificationRequired"
        }
        for field in data.keys():
            if field not in valid_fields:
                self.warnings.append(
                    f"{path}.structuredData.{field}: Unexpected field for 'Fuel Limits & Specifications'. "
                    f"Valid fields are: {sorted(valid_fields)}"
                )
    
    def _validate_emission_limits_logic(self, limits_list: List[Dict]):
        """Custom validation for emission limits."""
        if not isinstance(limits_list, list):
            return
        
        for idx, limit in enumerate(limits_list):
            if not isinstance(limit, dict):
                continue
            
            path = f"emissionLimits[{idx}]"
            
            # Validate cross-references
            applies_to = limit.get("appliesTo", [])
            if isinstance(applies_to, list):
                for ref_idx, ref_no in enumerate(applies_to):
                    if isinstance(ref_no, str) and ref_no:
                        if ref_no not in self.equipment_reference_nos:
                            self.warnings.append(
                                f"{path}.appliesTo[{ref_idx}]: Reference '{ref_no}' not found in "
                                f"equipmentSummary reference numbers. Check for exact match "
                                f"(spaces, dashes, capitalization)."
                            )


def validate_file(file_path: str, schema_path: str = None) -> Tuple[bool, List[str], List[str]]:
    """
    Validate a JSON file against the permit data schema.
    
    Args:
        file_path: Path to the JSON file to validate
        schema_path: Path to JSON schema file (optional)
    
    Returns:
        Tuple of (is_valid, errors, warnings)
    """
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except FileNotFoundError:
        return False, [f"File not found: {file_path}"], []
    except json.JSONDecodeError as e:
        return False, [f"Invalid JSON: {e}"], []
    except Exception as e:
        return False, [f"Error reading file: {e}"], []
    
    try:
        validator = PermitDataValidator(schema_path)
        return validator.validate(data)
    except FileNotFoundError:
        return False, [f"Schema file not found: {schema_path or 'schema.json'}"], []
    except json.JSONDecodeError as e:
        return False, [f"Invalid schema JSON: {e}"], []
    except Exception as e:
        return False, [f"Validation error: {e}"], []


def validate_directory(directory_path: str, schema_path: str = None, 
                      recursive: bool = True) -> Dict[str, Any]:
    """
    Validate all JSON files in a directory.
    
    Args:
        directory_path: Path to directory containing JSON files
        schema_path: Path to JSON schema file (optional)
        recursive: If True, search subdirectories
    
    Returns:
        Dictionary with validation results for each file
    """
    dir_path = Path(directory_path)
    
    if not dir_path.exists():
        return {"error": f"Directory not found: {directory_path}"}
    
    pattern = "**/*.json" if recursive else "*.json"
    json_files = list(dir_path.glob(pattern))
    
    # Exclude schema file from validation
    if schema_path:
        schema_file = Path(schema_path).resolve()
        json_files = [f for f in json_files if f.resolve() != schema_file]
    
    results = {
        "total_files": len(json_files),
        "valid_files": 0,
        "invalid_files": 0,
        "files": {}
    }
    
    for json_file in json_files:
        is_valid, errors, warnings = validate_file(str(json_file), schema_path)
        
        relative_path = json_file.relative_to(dir_path)
        results["files"][str(relative_path)] = {
            "valid": is_valid,
            "errors": errors,
            "warnings": warnings
        }
        
        if is_valid:
            results["valid_files"] += 1
        else:
            results["invalid_files"] += 1
    
    return results


def main():
    """Command-line interface for validation."""
    import argparse
    
    parser = argparse.ArgumentParser(
        description="Validate air permit extraction JSON files against schema"
    )
    parser.add_argument(
        "path",
        help="Path to JSON file or directory to validate"
    )
    parser.add_argument(
        "--schema",
        "-s",
        help="Path to JSON schema file (default: schema.json in same directory as validator)"
    )
    parser.add_argument(
        "--no-recursive",
        action="store_true",
        help="Don't search subdirectories (only for directory validation)"
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Show warnings in addition to errors"
    )
    
    args = parser.parse_args()
    
    path = Path(args.path)
    
    if path.is_file():
        # Validate single file
        is_valid, errors, warnings = validate_file(str(path), args.schema)
        
        print(f"\n{'='*70}")
        print(f"File: {path.name}")
        print(f"{'='*70}")
        
        if is_valid:
            print("✓ VALID")
        else:
            print("✗ INVALID")
        
        if errors:
            print(f"\nErrors ({len(errors)}):")
            for error in errors:
                print(f"  • {error}")
        
        if args.verbose and warnings:
            print(f"\nWarnings ({len(warnings)}):")
            for warning in warnings:
                print(f"  • {warning}")
        
        print()
        exit(0 if is_valid else 1)
    
    elif path.is_dir():
        # Validate directory
        results = validate_directory(str(path), args.schema, recursive=not args.no_recursive)
        
        if "error" in results:
            print(f"Error: {results['error']}")
            exit(1)
        
        print(f"\n{'='*70}")
        print(f"Directory: {path}")
        print(f"{'='*70}")
        print(f"Total files: {results['total_files']}")
        print(f"Valid: {results['valid_files']}")
        print(f"Invalid: {results['invalid_files']}")
        print()
        
        # Show details for invalid files
        for file_path, file_results in results["files"].items():
            if not file_results["valid"]:
                print(f"\n{file_path}:")
                for error in file_results["errors"]:
                    print(f"  • {error}")
                
                if args.verbose and file_results["warnings"]:
                    print("  Warnings:")
                    for warning in file_results["warnings"]:
                        print(f"    • {warning}")
        
        exit(0 if results["invalid_files"] == 0 else 1)
    
    else:
        print(f"Error: Path not found: {path}")
        exit(1)


if __name__ == "__main__":
    main()
