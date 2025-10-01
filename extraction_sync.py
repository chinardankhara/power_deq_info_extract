# To run this code you need to install the following dependencies:
# pip install google-genai python-dotenv

import os
from pathlib import Path
import pandas as pd
from google import genai
from google.genai import types
import json
import logging
from datetime import datetime
import re
from dotenv import load_dotenv
import time

load_dotenv()
# Set up logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def extract_date_from_filename(filename):
    """
    Extract ISO date from filename like '52281_2025-07-10.pdf'
    """
    match = re.search(r'_(\d{4}-\d{2}-\d{2})\.pdf$', filename)
    if match:
        return match.group(1)
    return None

def extract_registration_from_filename(filename):
    """
    Extract registration number from filename like '52281_2025-07-10.pdf'
    """
    match = re.search(r'^(\d+)_', filename)
    if match:
        return match.group(1)
    return None

def process_pdf_with_gemini(pdf_path, client, model="gemini-flash-latest"):
    """
    Process a single PDF with Gemini API and extract structured data
    """
    try:
        logging.info(f"Processing {pdf_path.name}")
        
        # Read the PDF file as bytes
        with open(pdf_path, 'rb') as pdf_file:
            pdf_data = pdf_file.read()
        
        # Create content with PDF data and extraction prompt
        contents = [
            types.Content(
                role="user",
                parts=[
                    types.Part.from_bytes(
                        data=pdf_data,
                        mime_type='application/pdf',
                    ),
                    types.Part.from_text(
                        text="""You are an expert regulatory data extraction engine specializing in Virginia DEQ Air Permits. Your task is to parse the provided permit document text and extract all required information into a structured JSON format.

**CRITICAL INSTRUCTIONS:**

1.  **Adhere strictly to the provided JSON schema.** Do not add or omit any top-level keys (`dataCenterName`, `equipmentSummary`, `operationalLimits`, etc.).
2.  **Equipment Type Taxonomy:** For the `type` field within `equipmentSummary`, you **must** use one and only one of the following four categories. Do not invent or combine terms:
    *   `Constructed`: For new units authorized by the current permit action (e.g., "Equipment to be Constructed," "authorized to construct and operate").
    *   `Modified`: For existing units undergoing a major physical change detailed in the permit, such as the addition of a control device (e.g., SCR).
    *   `Previously Permitted`: For existing units covered by a previous permit and listed for continued operation (e.g., "Equipment to be Operated," "Equipment permitted prior to the date of this permit").
    *   `Exempt`: For auxiliary equipment (e.g., fuel tanks, boilers, water heaters) explicitly listed as exempt from air permitting requirements.
3.  **Capacity Extraction & Numeric Types:** Extract both electrical and mechanical capacity separately.
    *   `electricalCapacity_kW`, `mechanicalCapacity_bhp`, `gasUsage_MMBTUhr`, and `numberOfUnits` **must be extracted as pure numbers (integer or float)**, not strings.
    *   For `electricalCapacity_kW` and `mechanicalCapacity_bhp`, calculate and report the **TOTAL combined capacity** (e.g., if "Forty generators" each rated "3000 kW", report `120000`).
4.  **Control Technology Separation:** Distinguish between intrinsic engine design controls and external add-on devices.
    *   `controls`: Capture descriptions of inherent engine design features and good operating practices (e.g., "electronic fuel injection, turbocharged engine, and aftercooler," "good combustion practices").
    *   `addOnControlTechnology`: Capture external emission reduction equipment (e.g., "SCR - Steuler CERNOX," "Catalyzed Diesel Particulate Filter (cDPF)"). If no external device is mentioned, use "None".
5.  **Operational Limits Classification:** All operational limits must be classified into one of these 9 standardized categories:
    *   **Hours of Operation Limits**: All restrictions on duration of operation (run hours, annual operational constraints, time periods). Examples: "500 hours/year", "Run Hours (ELRP)", "Run Hours (Emergency)", "Annual Operational Constraint".
    *   **Fuel Limits & Specifications**: Requirements for fuel type, quality, quantity, and consumption. Examples: "Fuel Throughput", "Fuel Specification (Sulfur Content)", "Fuel Certification".
    *   **Emission Limits & Caps**: Direct limits on pollutant mass emissions over time periods. Examples: "Annual Emission Limit", "Total Emissions Limit", "Emission Cap".
    *   **Production & Capacity Limits**: Restrictions on electrical output, mechanical load, or operational intensity. Examples: "Electrical Output Limit", "Engine Load", "Operating Capacity Limit".
    *   **Control Device & Equipment Requirements**: Rules for pollution control equipment operation, temperature, and specifications. Examples: "SCR Operation", "Control Device Operating Temperature", "Control Device Specification".
    *   **Non-Ozone Operating Restrictions**: Rules dictating how, why, and when units operate, including emergency scenarios, grid programs, and general operating modes (excluding ozone season restrictions). Examples: "Operating Mode Restriction", "Emergency Power Generation", "Operating Purpose Restriction".
    *   **Ozone Season Operating Restrictions**: Specific restrictions that apply during ozone season periods. Examples: "Ozone Season Operating Restrictions", "Ozone Season Integration Restriction", "Ozone Season MCRT".
    *   **Monitoring, Testing, & Recordkeeping**: Procedural requirements for compliance verification. Examples: "Performance Testing Requirement", "Monitoring/Recordkeeping", "Fuel Monitoring Recalibration".
    *   **Other**: Any operational limits that don't fit into the above categories, including maintenance procedures and miscellaneous requirements. Examples: "Maintenance and Operation", "Operating Practices", "Construction Timing".
6.  **Operational Limit Details:** The `limitDetails` field must capture ALL granular information including numeric limits, units, scope, conditions, calculation periods, and any specific circumstances or exceptions.
7.  **Dates:** Extract dates in `YYYY-MM-DD` format. If a date is only a year (e.g., "2000"), use `YYYY`.
8.  **Fuel Type:** For the `fuelType` field, you **must** use one of `Diesel`, `Gas`, or `Dual Fuel`. If the equipment does not use fuel (e.g., a cooling tower) or the type is not specified, this field should be null.
9.  **Emergency Generator Flag:** For the `isEmergency` field, set it to `true` if the equipment description includes terms like 'emergency', 'EP', 'black start', or 'standby'. Otherwise, set it to `false`.
10. **Number of Units:** For the `numberOfUnits` field, extract the count of individual equipment items as a number. For example, "Forty (40) Cummins machines" should result in `40`. A single unit should be `1`.
11. **Operational Limit Linking:** The `appliesTo` field in the `operationalLimits` array **must** be a list containing the exact string values from the `referenceNos` field of the equipment it applies to. This allows for direct matching. For example, if a limit applies to equipment with `referenceNos` of "EG01-EG20", the `appliesTo` field should be `["EG01-EG20"]`.
12. **Emission Limit Linking:** The `appliesTo` field in the `emissionLimits` array **must** also be a list containing the exact string values from the `referenceNos` field of the equipment it applies to, enabling direct programmatic matching just like operational limits. For example, if an emission limit applies to equipment with `referenceNos` of "1 - 4", the `appliesTo` field should be `["1 - 4"]`.
13. **Emission Limit Value Separation:** For emission limits, separate the numeric value from its unit:
    *   `limitValue`: Extract as a pure number (e.g., from "41.16 lbs/hr" extract `41.16`)
    *   `limitUnit`: Extract the unit as a string (e.g., from "41.16 lbs/hr" extract `"lbs/hr"`)
    *   For complex visible emission limits like "10% opacity except during one six-minute period not exceeding 20%", use the primary limit value (`10`) and include conditions in the `limitUnit` field or `conditions` field.
"""
                    ),
                ],
            ),
        ]
        
        generate_content_config = types.GenerateContentConfig(
            temperature=0,
            response_mime_type="application/json",
            response_schema=genai.types.Schema(
                type=genai.types.Type.OBJECT,
                description="Schema for extracting core data from air permit documents. All data fields are defined within the 'properties' object.",
                required=["dataCenterName", "permitIssuanceDate", "registrationNumber", "location", "equipmentSummary", "operationalLimits", "emissionLimits"],
                properties={
                    "dataCenterName": genai.types.Schema(type=genai.types.Type.STRING, description="The full name of the data center or facility as listed in the permit."),
                    "permitIssuanceDate": genai.types.Schema(type=genai.types.Type.STRING, description="The official date when the permit was issued (YYYY-MM-DD).", format="date"),
                    "registrationNumber": genai.types.Schema(type=genai.types.Type.STRING, description="The unique registration number for the permit."),
                    "location": genai.types.Schema(type=genai.types.Type.STRING, description="A concise string describing the location, including county and full address if available."),
                    "equipmentSummary": genai.types.Schema(
                        type=genai.types.Type.ARRAY,
                        description="A summary list of all equipment units, differentiating between constructed and previously permitted.",
                        items=genai.types.Schema(
                            type=genai.types.Type.OBJECT,
                            required=["type", "referenceNos", "description", "ratedCapacity", "numberOfUnits"],
                            properties={
                                "type": genai.types.Schema(type=genai.types.Type.STRING, description="Equipment type taxonomy - must be one of the four specified categories.", enum=["Constructed", "Modified", "Previously Permitted", "Exempt"]),
                                "referenceNos": genai.types.Schema(type=genai.types.Type.STRING, description="The reference number(s) for the equipment (e.g., 'G-1', '1 through 26', 'CT01 through CT11')."),
                                "description": genai.types.Schema(type=genai.types.Type.STRING, description="A concise description of the equipment, including make, model, and primary function (e.g., 'Caterpillar Model 3512 Diesel Generator', 'MTU 20V4000G83L 6 ECT emergency diesel engine gen-sets', 'SPX Marley Cooling Towers')."),
                                "ratedCapacity": genai.types.Schema(type=genai.types.Type.STRING, description="The rated capacity of a single equipment unit, including units (e.g., '1,135 kW', '2,500 ekW 3,633 bhp (each)', '2,400 gpm (each)')."),
                                "numberOfUnits": genai.types.Schema(type=genai.types.Type.NUMBER, description="The integer count of individual equipment units in this group (e.g., for 'Forty (40) generators', this value would be 40)."),
                                "fuelType": genai.types.Schema(type=genai.types.Type.STRING, description="The type of fuel used by the equipment. Must be one of the specified values.", enum=["Diesel", "Gas", "Dual Fuel"]),
                                "isEmergency": genai.types.Schema(type=genai.types.Type.BOOLEAN, description="Set to true if the equipment is designated for emergency, standby, EP, or black start purposes."),
                                "electricalCapacity_kW": genai.types.Schema(type=genai.types.Type.NUMBER, description="TOTAL combined electrical capacity in kilowatts (kW or ekW) as a number. For multiple units, this is the calculated combined capacity. Null if not specified."),
                                "mechanicalCapacity_bhp": genai.types.Schema(type=genai.types.Type.NUMBER, description="TOTAL combined mechanical capacity in horsepower (HP or bhp) as a number. For multiple units, this is the calculated combined capacity. Null if not specified."),
                                "gasUsage_MMBTUhr": genai.types.Schema(type=genai.types.Type.NUMBER, description="For gas-fired equipment, the heat input rate in MMBTU/hr as a number. Null if not applicable."),
                                "controls": genai.types.Schema(type=genai.types.Type.STRING, description="Inherent engine design features and good operating practices (e.g., 'electronic fuel injection, turbocharged engine, and aftercooler', 'good combustion practices')."),
                                "addOnControlTechnology": genai.types.Schema(type=genai.types.Type.STRING, description="External emission reduction equipment (e.g., 'SCR - Steuler CERNOX', 'Catalyzed Diesel Particulate Filter (cDPF)'). Use 'None' if no external device is mentioned."),
                                "originalPermitDate": genai.types.Schema(type=genai.types.Type.STRING, description="The original permit date for this specific equipment, if explicitly stated and different from the main permit issuance date (YYYY-MM-DD).", format="date"),
                            },
                        ),
                    ),
                    "operationalLimits": genai.types.Schema(
                        type=genai.types.Type.ARRAY,
                        description="A list of all key operational limits mentioned in the permit, classified into 9 standardized categories.",
                        items=genai.types.Schema(
                            type=genai.types.Type.OBJECT,
                            required=["category", "appliesTo", "limitDetails"],
                            properties={
                                "category": genai.types.Schema(
                                    type=genai.types.Type.STRING, 
                                    description="Standardized operational limit category - must be one of the 9 specified categories.",
                                    enum=[
                                        "Hours of Operation Limits",
                                        "Fuel Limits & Specifications", 
                                        "Emission Limits & Caps",
                                        "Production & Capacity Limits",
                                        "Control Device & Equipment Requirements",
                                        "Non-Ozone Operating Restrictions",
                                        "Ozone Season Operating Restrictions",
                                        "Monitoring, Testing, & Recordkeeping",
                                        "Other"
                                    ]
                                ),
                                "appliesTo": genai.types.Schema(
                                    type=genai.types.Type.ARRAY,
                                    description="A list of exact 'referenceNos' strings from the equipmentSummary this limit applies to, enabling direct programmatic matching.",
                                    items=genai.types.Schema(type=genai.types.Type.STRING)
                                ),
                                "limitDetails": genai.types.Schema(type=genai.types.Type.STRING, description="The full, descriptive text of the operational limit, including values, units, conditions, calculation periods, and all granular details."),
                            },
                        ),
                    ),
                    "emissionLimits": genai.types.Schema(
                        type=genai.types.Type.ARRAY,
                        description="A list of all key emission limits mentioned in the permit.",
                        items=genai.types.Schema(
                            type=genai.types.Type.OBJECT,
                            required=["type", "appliesTo", "pollutant", "limitValue", "limitUnit"],
                            properties={
                                "type": genai.types.Schema(type=genai.types.Type.STRING, description="Whether the limit is 'Hourly', 'Annual', or 'Visible Emissions'.", enum=["Hourly", "Annual", "Visible Emissions"]),
                                "appliesTo": genai.types.Schema(
                                    type=genai.types.Type.ARRAY,
                                    description="A list of exact 'referenceNos' strings from the equipmentSummary this limit applies to, enabling direct programmatic matching.",
                                    items=genai.types.Schema(type=genai.types.Type.STRING)
                                ),
                                "pollutant": genai.types.Schema(type=genai.types.Type.STRING, description="The pollutant(s) being limited (e.g., 'PM-10', 'Nitrogen Oxides (as NO2)', 'Opacity')."),
                                "limitValue": genai.types.Schema(type=genai.types.Type.NUMBER, description="The numeric limit value as a number (e.g., 1.2, 96.03, 10). For Visible Emissions with conditions, use the primary limit value."),
                                "limitUnit": genai.types.Schema(type=genai.types.Type.STRING, description="The unit of the limit value (e.g., 'lbs/hr', 'tpy', 'percent opacity', 'ppm', 'g/dscm'). For complex visible emission limits, include conditions here."),
                                "conditions": genai.types.Schema(type=genai.types.Type.STRING, description="Any specific conditions or context for this limit (e.g., 'Uncontrolled by SCR', 'During startup and shutdown', 'Calculated monthly as consecutive 12-month period')."),
                            },
                        ),
                    ),
                },
            ),
        )

        # Generate content using streaming
        response_text = ""
        for chunk in client.models.generate_content_stream(
            model=model,
            contents=contents,
            config=generate_content_config,
        ):
            response_text += chunk.text

        # Parse the JSON response
        try:
            extracted_data = json.loads(response_text)
            
            # Add metadata
            extracted_data['source_file'] = pdf_path.name
            extracted_data['processing_date'] = datetime.now().isoformat()
            
            # Create filename using registration number and ISO date from the PDF filename
            registration_no = extract_registration_from_filename(pdf_path.name)
            iso_date = extract_date_from_filename(pdf_path.name)
            
            if registration_no and iso_date:
                json_filename = f"{registration_no}_{iso_date}.json"
            else:
                # Fallback to original filename
                json_filename = pdf_path.stem + '.json'
            
            logging.info(f"Successfully processed {pdf_path.name} -> {json_filename}")
            return extracted_data, json_filename
            
        except json.JSONDecodeError as e:
            logging.error(f"Failed to parse JSON response for {pdf_path.name}: {e}")
            logging.error(f"Response text was: {response_text}")
            return None, None
            
    except Exception as e:
        logging.error(f"Error processing {pdf_path.name}: {e}")
        return None, None

def process_pdf_with_gemini_year(pdf_path, client, output_dir, model="gemini-flash-latest"):
    """
    Process a single PDF and save to year-specific directory
    """
    # Process the PDF
    extracted_data, json_filename = process_pdf_with_gemini(pdf_path, client, model)
    
    if extracted_data and json_filename:
        # Save to year-specific directory
        json_path = output_dir / json_filename
        
        with open(json_path, 'w', encoding='utf-8') as f:
            json.dump(extracted_data, f, indent=2, ensure_ascii=False)
        
        print(f"✓ SAVED: {json_filename}")
        
        # Show progress for this year
        completed_files = len(list(output_dir.glob("*.json")))
        print(f"Year progress: {completed_files} files completed")
        
        return extracted_data, json_filename
    
    return None, None

def process_all_pdfs():
    """
    Process all PDFs in year-based subdirectories under raw_pdfs
    """
    # Initialize the Gemini client
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        print("Error: GEMINI_API_KEY environment variable not set!")
        return
    client = genai.Client(api_key=api_key)
    
    # Directory containing year-based PDF folders
    raw_pdfs_base = Path('raw_pdfs')
    if not raw_pdfs_base.exists():
        print(f"Error: {raw_pdfs_base} directory not found!")
        return
    
    # Get all year subdirectories
    year_dirs = sorted([d for d in raw_pdfs_base.iterdir() if d.is_dir() and d.name.isdigit()])
    if not year_dirs:
        print(f"No year subdirectories found in {raw_pdfs_base}")
        return
    
    print(f"Found {len(year_dirs)} year directories: {[d.name for d in year_dirs]}")
    
    # Create base output directory
    json_data_base = Path('extracted_data')
    json_data_base.mkdir(exist_ok=True)
    
    # Process each year directory
    total_successful = 0
    total_failed = 0
    
    for year_dir in year_dirs:
        year = year_dir.name
        print(f"\n{'='*60}\nProcessing Year: {year}\n{'='*60}")
        
        pdf_files = list(year_dir.glob("*.pdf"))
        if not pdf_files:
            print(f"No PDF files found in {year_dir}")
            continue
        
        print(f"Found {len(pdf_files)} PDF files for year {year}")
        
        year_output_dir = json_data_base / year
        year_output_dir.mkdir(exist_ok=True)
        
        year_successful = 0
        year_failed = 0
        
        for i, pdf_path in enumerate(pdf_files, 1):
            print(f"\n[{year}] [{i}/{len(pdf_files)}] Processing: {pdf_path.name}")
            start_time = time.time()
            
            extracted_data, json_filename = process_pdf_with_gemini_year(pdf_path, client, year_output_dir)
            
            elapsed_time = time.time() - start_time
            
            if extracted_data and json_filename:
                year_successful += 1
                print(f"✓ Completed in {elapsed_time:.1f}s")
            else:
                year_failed += 1
                print(f"✗ Failed: {pdf_path.name}")
            
            if i < len(pdf_files):
                time.sleep(1)
        
        total_successful += year_successful
        total_failed += year_failed
        print(f"\nYear {year} Summary: {year_successful} successful, {year_failed} failed")
    
    print(f"\n{'='*60}\nOverall Summary:\nTotal Successful: {total_successful}\nTotal Failed: {total_failed}\n{'='*60}")

if __name__ == "__main__":
    process_all_pdfs()