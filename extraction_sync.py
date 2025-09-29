# To run this code you need to install the following dependencies:
# pip install google-genai

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

1. **Adhere strictly to the provided JSON schema.** Do not add or omit any top-level keys (`dataCenterName`, `equipmentSummary`, `operationalLimits`, etc.).
2. **Equipment Type Taxonomy:** For the `type` field within `equipmentSummary`, you **must** use one and only one of the following four categories. Do not invent or combine terms:
   - `Constructed`: For new units authorized by the current permit action (e.g., "Equipment to be Constructed," "authorized to construct and operate").
   - `Modified`: For existing units undergoing a major physical change detailed in the permit, such as the addition of a control device (e.g., SCR).
   - `Previously Permitted`: For existing units covered by a previous permit and listed for continued operation (e.g., "Equipment to be Operated," "Equipment permitted prior to the date of this permit").
   - `Exempt`: For auxiliary equipment (e.g., fuel tanks, boilers, water heaters) explicitly listed as exempt from air permitting requirements.
3. **Capacity Extraction:** Extract both electrical and mechanical capacity separately.
   - `electricalCapacity_kW`: Extract the kilowatt (kW or ekW) value and unit. **For multiple units, calculate and report the TOTAL combined capacity** (e.g., if "Two generators" each rated "1000 kW", report "2000 kW").
   - `mechanicalCapacity_bhp`: Extract the horsepower (HP or bhp) value and unit. **For multiple units, calculate and report the TOTAL combined capacity** (e.g., if "Three engines" each rated "500 bhp", report "1500 bhp").
   - If only one capacity type is listed, populate that field and leave the other null.
4. **Control Technology Separation:** Distinguish between intrinsic engine design controls and external add-on devices.
   - `controls`: Capture descriptions of inherent engine design features and good operating practices (e.g., "electronic fuel injection, turbocharged engine, and aftercooler," "good combustion practices").
   - `addOnControlTechnology`: Capture external emission reduction equipment (e.g., "SCR - Steuler CERNOX," "Catalyzed Diesel Particulate Filter (cDPF)"). If no external device is mentioned, use "None".
5. **Run Hours and Operational Limits:** Extract all specific run hour limits. The `limitDetails` must clearly state the numeric limit, the unit (e.g., hours/year), and the scope (e.g., "each unit," "combined," "for ELRP only"). If multiple limits apply to the same equipment (e.g., 500 hours/year total, 60 hours/year for ELRP), create separate entries in the `operationalLimits` array.
6. **Dates:** Extract dates in `YYYY-MM-DD` format. If a date is only a year (e.g., "2000"), use `YYYY`.

Be thorough and accurate in extracting all numerical values, dates, and technical specifications."""
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
                    "dataCenterName": genai.types.Schema(
                        type=genai.types.Type.STRING,
                        description="The full name of the data center or facility as listed in the permit.",
                    ),
                    "permitIssuanceDate": genai.types.Schema(
                        type=genai.types.Type.STRING,
                        description="The official date when the permit was issued (YYYY-MM-DD).",
                        format="date",
                    ),
                    "registrationNumber": genai.types.Schema(
                        type=genai.types.Type.STRING,
                        description="The unique registration number for the permit.",
                    ),
                    "location": genai.types.Schema(
                        type=genai.types.Type.STRING,
                        description="A concise string describing the location, including county and full address if available.",
                    ),
                    "equipmentSummary": genai.types.Schema(
                        type=genai.types.Type.ARRAY,
                        description="A summary list of all equipment units, differentiating between constructed and previously permitted.",
                        items=genai.types.Schema(
                            type=genai.types.Type.OBJECT,
                            required=["type", "referenceNos", "description", "ratedCapacity"],
                            properties={
                                "type": genai.types.Schema(
                                    type=genai.types.Type.STRING,
                                    description="Equipment type taxonomy - must be one of the four specified categories.",
                                    enum=["Constructed", "Modified", "Previously Permitted", "Exempt"],
                                ),
                                "referenceNos": genai.types.Schema(
                                    type=genai.types.Type.STRING,
                                    description="The reference number(s) for the equipment (e.g., 'G-1', '1 through 26', 'CT01 through CT11').",
                                ),
                                "description": genai.types.Schema(
                                    type=genai.types.Type.STRING,
                                    description="A concise description of the equipment, including make, model, and primary function (e.g., 'Caterpillar Model 3512 Diesel Generator', 'MTU 20V4000G83L 6 ECT emergency diesel engine gen-sets', 'SPX Marley Cooling Towers').",
                                ),
                                "ratedCapacity": genai.types.Schema(
                                    type=genai.types.Type.STRING,
                                    description="The rated capacity of the equipment, including units (e.g., '1,135 kW', '2,500 ekW 3,633 bhp (each)', '2,400 gpm (each)').",
                                ),
                                "electricalCapacity_kW": genai.types.Schema(
                                    type=genai.types.Type.STRING,
                                    description="TOTAL electrical capacity in kilowatts (kW or ekW) with units. For multiple units, calculate combined capacity (e.g., 'Two generators' at '1000 kW each' = '2000 kW'). Null if not specified.",
                                ),
                                "mechanicalCapacity_bhp": genai.types.Schema(
                                    type=genai.types.Type.STRING,
                                    description="TOTAL mechanical capacity in horsepower (HP or bhp) with units. For multiple units, calculate combined capacity (e.g., 'Three engines' at '500 bhp each' = '1500 bhp'). Null if not specified.",
                                ),
                                "controls": genai.types.Schema(
                                    type=genai.types.Type.STRING,
                                    description="Inherent engine design features and good operating practices (e.g., 'electronic fuel injection, turbocharged engine, and aftercooler', 'good combustion practices').",
                                ),
                                "addOnControlTechnology": genai.types.Schema(
                                    type=genai.types.Type.STRING,
                                    description="External emission reduction equipment (e.g., 'SCR - Steuler CERNOX', 'Catalyzed Diesel Particulate Filter (cDPF)'). Use 'None' if no external device is mentioned.",
                                ),
                                "originalPermitDate": genai.types.Schema(
                                    type=genai.types.Type.STRING,
                                    description="The original permit date for this specific equipment, if explicitly stated and different from the main permit issuance date (YYYY-MM-DD).",
                                    format="date",
                                ),
                            },
                        ),
                    ),
                    "operationalLimits": genai.types.Schema(
                        type=genai.types.Type.ARRAY,
                        description="A list of all key operational limits mentioned in the permit.",
                        items=genai.types.Schema(
                            type=genai.types.Type.OBJECT,
                            required=["category", "appliesTo", "limitDetails"],
                            properties={
                                "category": genai.types.Schema(
                                    type=genai.types.Type.STRING,
                                    description="Broad category of the limit, e.g., 'Run Hours', 'Fuel Specification', 'Fuel Throughput', 'Ozone Season Operating Restrictions', 'Cooling Tower Limit'.",
                                ),
                                "appliesTo": genai.types.Schema(
                                    type=genai.types.Type.STRING,
                                    description="Which equipment or group the limit applies to (e.g., 'Each generator', 'All emergency diesel gen-sets', 'CT01 through CT11').",
                                ),
                                "limitDetails": genai.types.Schema(
                                    type=genai.types.Type.STRING,
                                    description="The full, descriptive text of the operational limit, including values, units, conditions, and calculation periods.",
                                ),
                            },
                        ),
                    ),
                    "emissionLimits": genai.types.Schema(
                        type=genai.types.Type.ARRAY,
                        description="A list of all key emission limits mentioned in the permit.",
                        items=genai.types.Schema(
                            type=genai.types.Type.OBJECT,
                            required=["type", "appliesTo", "pollutant", "limitValue"],
                            properties={
                                "type": genai.types.Schema(
                                    type=genai.types.Type.STRING,
                                    description="Whether the limit is 'Hourly', 'Annual', or 'Visible Emissions'.",
                                    enum=["Hourly", "Annual", "Visible Emissions"],
                                ),
                                "appliesTo": genai.types.Schema(
                                    type=genai.types.Type.STRING,
                                    description="Which equipment or group the limit applies to (e.g., 'Each generator', 'Caterpillar 3512 gen-sets (G-1, G-2)', 'All Units Combined').",
                                ),
                                "pollutant": genai.types.Schema(
                                    type=genai.types.Type.STRING,
                                    description="The pollutant(s) being limited (e.g., 'PM-10', 'Nitrogen Oxides (as NO2)', 'Opacity').",
                                ),
                                "limitValue": genai.types.Schema(
                                    type=genai.types.Type.STRING,
                                    description="The quantitative limit value with units (e.g., '1.2 lbs/hr', '96.03 tpy', '10 percent opacity'). For Visible Emissions, include specific conditions if present (e.g., '10% opacity except during one six-minute period not exceeding 20%').",
                                ),
                                "conditions": genai.types.Schema(
                                    type=genai.types.Type.STRING,
                                    description="Any specific conditions or context for this limit (e.g., 'Uncontrolled by SCR', 'During startup and shutdown', 'Calculated monthly as consecutive 12-month period').",
                                ),
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
    client = genai.Client(
        api_key=os.environ.get("GEMINI_API_KEY"),
    )
    
    # Check if API key is set
    if not os.environ.get("GEMINI_API_KEY"):
        print("Error: GEMINI_API_KEY environment variable not set!")
        print("Please set it with: export GEMINI_API_KEY='your-api-key'")
        return
    
    # Directory containing year-based PDF folders
    raw_pdfs_base = Path('raw_pdfs')
    
    if not raw_pdfs_base.exists():
        print(f"Error: {raw_pdfs_base} directory not found!")
        return
    
    # Get all year subdirectories
    year_dirs = [d for d in raw_pdfs_base.iterdir() if d.is_dir() and d.name.isdigit()]
    
    if not year_dirs:
        print(f"No year subdirectories found in {raw_pdfs_base}")
        return
    
    year_dirs.sort()  # Process in chronological order
    print(f"Found {len(year_dirs)} year directories: {[d.name for d in year_dirs]}")
    
    # Create base output directory
    json_data_base = Path('json_data')
    json_data_base.mkdir(exist_ok=True)
    
    # Process each year directory
    total_successful = 0
    total_failed = 0
    total_files = 0
    
    for year_dir in year_dirs:
        year = year_dir.name
        print(f"\n{'='*60}")
        print(f"Processing Year: {year}")
        print(f"{'='*60}")
        
        # Get all PDF files in this year directory
        pdf_files = list(year_dir.glob("*.pdf"))
        
        if not pdf_files:
            print(f"No PDF files found in {year_dir}")
            continue
        
        total_files += len(pdf_files)
        print(f"Found {len(pdf_files)} PDF files for year {year}")
        
        # Create year-specific output directory
        year_output_dir = json_data_base / year
        year_output_dir.mkdir(exist_ok=True)
        
        # Process each PDF in this year
        year_successful = 0
        year_failed = 0
        
        for i, pdf_path in enumerate(pdf_files, 1):
            print(f"\n[{year}] [{i}/{len(pdf_files)}] Processing: {pdf_path.name}")
            start_time = time.time()
            
            # Update the process function to use year-specific output directory
            extracted_data, json_filename = process_pdf_with_gemini_year(pdf_path, client, year_output_dir)
            
            elapsed_time = time.time() - start_time
            
            if extracted_data and json_filename:
                year_successful += 1
                total_successful += 1
                print(f"✓ Completed in {elapsed_time:.1f}s")
            else:
                print(f"✗ Failed: {pdf_path.name}")
                year_failed += 1
                total_failed += 1
            
            # Small delay between requests to be respectful to the API
            if i < len(pdf_files):
                time.sleep(1)
        
        
        print(f"\nYear {year} Summary: {year_successful} successful, {year_failed} failed")
    
if __name__ == "__main__":
    process_all_pdfs()
