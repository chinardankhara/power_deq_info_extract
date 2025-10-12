"""
JSON Validator for Air Permit Data Extraction Schema

Performs comprehensive validation of extracted permit data against the schema:
- Checks required fields presence and nesting structure
- Validates data types (strings, numbers, booleans, arrays, objects)
- Enforces enum constraints
- Validates date formats (YYYY-MM-DD)
- Ensures non-negative numeric values
- Validates cross-references between equipmentSummary and operational/emission limits
"""

import json
from datetime import datetime
from typing import Any, Dict, List, Tuple
from pathlib import Path


class PermitDataValidator:
    """Validator for air permit extraction data following the defined schema."""
    
    # Schema enums
    EQUIPMENT_TYPES = {"Constructed", "Modified", "Previously Permitted", "Exempt"}
    FUEL_TYPES = {"Diesel", "Gas", "Dual Fuel"}
    OPERATIONAL_CATEGORIES = {
        "Hours of Operation Limits",
        "Fuel Limits & Specifications",
        "Emission Limits & Caps",
        "Production & Capacity Limits",
        "Control Device & Equipment Requirements",
        "Non-Ozone Operating Restrictions",
        "Ozone Season Operating Restrictions",
        "Monitoring, Testing, & Recordkeeping",
        "Other"
    }
    EMISSION_TYPES = {"Hourly", "Annual", "Visible Emissions"}
    
    def __init__(self):
        self.errors: List[str] = []
        self.warnings: List[str] = []
        self.equipment_reference_nos: set = set()
    
    def validate(self, data: Dict[str, Any]) -> Tuple[bool, List[str], List[str]]:
        """
        Validate permit data against schema.
        
        Returns:
            Tuple of (is_valid, errors, warnings)
        """
        self.errors = []
        self.warnings = []
        self.equipment_reference_nos = set()
        
        # Check top-level structure
        if not isinstance(data, dict):
            self.errors.append("Root data must be a JSON object/dictionary")
            return False, self.errors, self.warnings
        
        # Validate required top-level fields
        self._validate_required_fields(
            data, 
            ["dataCenterName", "permitIssuanceDate", "registrationNumber", 
             "location", "equipmentSummary", "operationalLimits", "emissionLimits"],
            "root"
        )
        
        # Validate each section
        if "dataCenterName" in data:
            self._validate_string(data["dataCenterName"], "dataCenterName", required=True)
        
        if "permitIssuanceDate" in data:
            self._validate_date(data["permitIssuanceDate"], "permitIssuanceDate")
        
        if "registrationNumber" in data:
            self._validate_string(data["registrationNumber"], "registrationNumber", required=True)
        
        if "location" in data:
            self._validate_string(data["location"], "location", required=True)
        
        if "equipmentSummary" in data:
            self._validate_equipment_summary(data["equipmentSummary"])
        
        if "operationalLimits" in data:
            self._validate_operational_limits(data["operationalLimits"])
        
        if "emissionLimits" in data:
            self._validate_emission_limits(data["emissionLimits"])
        
        is_valid = len(self.errors) == 0
        return is_valid, self.errors, self.warnings
    
    def _validate_required_fields(self, obj: Dict, required: List[str], path: str):
        """Check that all required fields are present."""
        for field in required:
            if field not in obj:
                self.errors.append(f"{path}: Missing required field '{field}'")
    
    def _validate_string(self, value: Any, field_name: str, required: bool = False):
        """Validate string field."""
        if value is None:
            if required:
                self.errors.append(f"{field_name}: Required string field is null")
            return
        
        if not isinstance(value, str):
            self.errors.append(f"{field_name}: Expected string, got {type(value).__name__}")
        elif required and not value.strip():
            self.errors.append(f"{field_name}: Required string field is empty")
    
    def _validate_number(self, value: Any, field_name: str, allow_negative: bool = False, 
                        allow_null: bool = True):
        """Validate numeric field."""
        if value is None:
            if not allow_null:
                self.errors.append(f"{field_name}: Number field cannot be null")
            return
        
        if not isinstance(value, (int, float)):
            self.errors.append(f"{field_name}: Expected number, got {type(value).__name__}")
        elif not allow_negative and value < 0:
            self.errors.append(f"{field_name}: Number must be non-negative, got {value}")
        elif isinstance(value, bool):
            # In Python, bool is a subclass of int, so we need to explicitly reject booleans
            self.errors.append(f"{field_name}: Expected number, got boolean")
    
    def _validate_boolean(self, value: Any, field_name: str, allow_null: bool = True):
        """Validate boolean field."""
        if value is None:
            if not allow_null:
                self.errors.append(f"{field_name}: Boolean field cannot be null")
            return
        
        if not isinstance(value, bool):
            self.errors.append(f"{field_name}: Expected boolean, got {type(value).__name__}")
    
    def _validate_date(self, value: Any, field_name: str, allow_null: bool = False):
        """Validate date string in YYYY-MM-DD format."""
        if value is None:
            if not allow_null:
                self.errors.append(f"{field_name}: Date field cannot be null")
            return
        
        if not isinstance(value, str):
            self.errors.append(f"{field_name}: Date must be a string, got {type(value).__name__}")
            return
        
        try:
            parsed = datetime.strptime(value, "%Y-%m-%d")
            # Basic sanity check on year
            if parsed.year < 1900 or parsed.year > 2100:
                self.warnings.append(f"{field_name}: Date year {parsed.year} seems unusual")
        except ValueError:
            self.errors.append(f"{field_name}: Invalid date format '{value}', expected YYYY-MM-DD")
    
    def _validate_enum(self, value: Any, field_name: str, valid_values: set, 
                      allow_null: bool = True):
        """Validate enum field."""
        if value is None:
            if not allow_null:
                self.errors.append(f"{field_name}: Enum field cannot be null")
            return
        
        if not isinstance(value, str):
            self.errors.append(f"{field_name}: Enum must be a string, got {type(value).__name__}")
        elif value not in valid_values:
            self.errors.append(
                f"{field_name}: Invalid enum value '{value}'. "
                f"Must be one of: {sorted(valid_values)}"
            )
    
    def _validate_array(self, value: Any, field_name: str, allow_empty: bool = False):
        """Validate array field."""
        if not isinstance(value, list):
            self.errors.append(f"{field_name}: Expected array, got {type(value).__name__}")
            return False
        
        if not allow_empty and len(value) == 0:
            self.warnings.append(f"{field_name}: Array is empty")
        
        return True
    
    def _validate_equipment_summary(self, equipment_list: List[Dict]):
        """Validate equipmentSummary array."""
        if not self._validate_array(equipment_list, "equipmentSummary"):
            return
        
        for idx, equipment in enumerate(equipment_list):
            path = f"equipmentSummary[{idx}]"
            
            if not isinstance(equipment, dict):
                self.errors.append(f"{path}: Expected object, got {type(equipment).__name__}")
                continue
            
            # Check required fields
            self._validate_required_fields(
                equipment,
                ["type", "referenceNos", "description", "ratedCapacity", "numberOfUnits"],
                path
            )
            
            # Validate each field
            if "type" in equipment:
                self._validate_enum(equipment["type"], f"{path}.type", 
                                   self.EQUIPMENT_TYPES, allow_null=False)
            
            if "referenceNos" in equipment:
                ref_nos = equipment["referenceNos"]
                self._validate_string(ref_nos, f"{path}.referenceNos", required=True)
                if isinstance(ref_nos, str):
                    self.equipment_reference_nos.add(ref_nos)
            
            if "description" in equipment:
                self._validate_string(equipment["description"], f"{path}.description", 
                                     required=True)
            
            if "ratedCapacity" in equipment:
                self._validate_string(equipment["ratedCapacity"], f"{path}.ratedCapacity", 
                                     required=True)
            
            if "numberOfUnits" in equipment:
                num_units = equipment["numberOfUnits"]
                self._validate_number(num_units, f"{path}.numberOfUnits", 
                                     allow_null=False)
                # Check if it's a positive integer (even if stored as float)
                if isinstance(num_units, (int, float)) and not isinstance(num_units, bool):
                    if num_units <= 0:
                        self.errors.append(
                            f"{path}.numberOfUnits: Must be positive, got {num_units}"
                        )
                    elif num_units != int(num_units):
                        self.warnings.append(
                            f"{path}.numberOfUnits: Expected integer count, got {num_units}"
                        )
            
            # Optional fields
            if "fuelType" in equipment:
                self._validate_enum(equipment["fuelType"], f"{path}.fuelType", 
                                   self.FUEL_TYPES)
            
            if "isEmergency" in equipment:
                self._validate_boolean(equipment["isEmergency"], f"{path}.isEmergency")
            
            if "electricalCapacity_kW" in equipment:
                self._validate_number(equipment["electricalCapacity_kW"], 
                                     f"{path}.electricalCapacity_kW")
            
            if "mechanicalCapacity_bhp" in equipment:
                self._validate_number(equipment["mechanicalCapacity_bhp"], 
                                     f"{path}.mechanicalCapacity_bhp")
            
            if "gasUsage_MMBTUhr" in equipment:
                self._validate_number(equipment["gasUsage_MMBTUhr"], 
                                     f"{path}.gasUsage_MMBTUhr")
            
            if "controls" in equipment:
                self._validate_string(equipment["controls"], f"{path}.controls")
            
            if "addOnControlTechnology" in equipment:
                self._validate_string(equipment["addOnControlTechnology"], 
                                     f"{path}.addOnControlTechnology")
            
            if "originalPermitDate" in equipment:
                self._validate_date(equipment["originalPermitDate"], 
                                   f"{path}.originalPermitDate", allow_null=True)
    
    def _validate_operational_limits(self, limits_list: List[Dict]):
        """Validate operationalLimits array."""
        if not self._validate_array(limits_list, "operationalLimits"):
            return
        
        for idx, limit in enumerate(limits_list):
            path = f"operationalLimits[{idx}]"
            
            if not isinstance(limit, dict):
                self.errors.append(f"{path}: Expected object, got {type(limit).__name__}")
                continue
            
            # Check required fields
            self._validate_required_fields(
                limit,
                ["category", "appliesTo", "limitDetails"],
                path
            )
            
            # Validate fields
            if "category" in limit:
                self._validate_enum(limit["category"], f"{path}.category", 
                                   self.OPERATIONAL_CATEGORIES, allow_null=False)
            
            if "appliesTo" in limit:
                applies_to = limit["appliesTo"]
                if not self._validate_array(applies_to, f"{path}.appliesTo", 
                                           allow_empty=True):
                    continue
                
                # Validate each reference number
                for ref_idx, ref_no in enumerate(applies_to):
                    ref_path = f"{path}.appliesTo[{ref_idx}]"
                    self._validate_string(ref_no, ref_path, required=True)
                    
                    # Cross-reference check
                    if isinstance(ref_no, str) and ref_no:
                        if ref_no not in self.equipment_reference_nos:
                            self.warnings.append(
                                f"{ref_path}: Reference '{ref_no}' not found in "
                                f"equipmentSummary reference numbers"
                            )
            
            if "limitDetails" in limit:
                self._validate_string(limit["limitDetails"], f"{path}.limitDetails", 
                                     required=True)
    
    def _validate_emission_limits(self, limits_list: List[Dict]):
        """Validate emissionLimits array."""
        if not self._validate_array(limits_list, "emissionLimits"):
            return
        
        for idx, limit in enumerate(limits_list):
            path = f"emissionLimits[{idx}]"
            
            if not isinstance(limit, dict):
                self.errors.append(f"{path}: Expected object, got {type(limit).__name__}")
                continue
            
            # Check required fields
            self._validate_required_fields(
                limit,
                ["type", "appliesTo", "pollutant", "limitValue", "limitUnit"],
                path
            )
            
            # Validate fields
            if "type" in limit:
                self._validate_enum(limit["type"], f"{path}.type", 
                                   self.EMISSION_TYPES, allow_null=False)
            
            if "appliesTo" in limit:
                applies_to = limit["appliesTo"]
                if not self._validate_array(applies_to, f"{path}.appliesTo", 
                                           allow_empty=True):
                    continue
                
                # Validate each reference number
                for ref_idx, ref_no in enumerate(applies_to):
                    ref_path = f"{path}.appliesTo[{ref_idx}]"
                    self._validate_string(ref_no, ref_path, required=True)
                    
                    # Cross-reference check
                    if isinstance(ref_no, str) and ref_no:
                        if ref_no not in self.equipment_reference_nos:
                            self.warnings.append(
                                f"{ref_path}: Reference '{ref_no}' not found in "
                                f"equipmentSummary reference numbers"
                            )
            
            if "pollutant" in limit:
                self._validate_string(limit["pollutant"], f"{path}.pollutant", 
                                     required=True)
            
            if "limitValue" in limit:
                self._validate_number(limit["limitValue"], f"{path}.limitValue", 
                                     allow_null=False)
            
            if "limitUnit" in limit:
                self._validate_string(limit["limitUnit"], f"{path}.limitUnit", 
                                     required=True)
            
            if "conditions" in limit:
                self._validate_string(limit["conditions"], f"{path}.conditions")


def validate_file(file_path: str) -> Tuple[bool, List[str], List[str]]:
    """
    Validate a JSON file against the permit data schema.
    
    Args:
        file_path: Path to the JSON file to validate
    
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
    
    validator = PermitDataValidator()
    return validator.validate(data)


def validate_directory(directory_path: str, recursive: bool = True) -> Dict[str, Any]:
    """
    Validate all JSON files in a directory.
    
    Args:
        directory_path: Path to directory containing JSON files
        recursive: If True, search subdirectories
    
    Returns:
        Dictionary with validation results for each file
    """
    dir_path = Path(directory_path)
    
    if not dir_path.exists():
        return {"error": f"Directory not found: {directory_path}"}
    
    pattern = "**/*.json" if recursive else "*.json"
    json_files = list(dir_path.glob(pattern))
    
    results = {
        "total_files": len(json_files),
        "valid_files": 0,
        "invalid_files": 0,
        "files": {}
    }
    
    for json_file in json_files:
        is_valid, errors, warnings = validate_file(str(json_file))
        
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
        is_valid, errors, warnings = validate_file(str(path))
        
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
        results = validate_directory(str(path), recursive=not args.no_recursive)
        
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
