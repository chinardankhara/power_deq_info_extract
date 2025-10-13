# To run this code you need to install the following dependencies:
# pip install google-genai python-dotenv

import os
from pathlib import Path
from google import genai
from google.genai import types
import json
import logging
from datetime import datetime
import re
from dotenv import load_dotenv
import time
import argparse

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

def load_extraction_prompt(prompt_file_path="extraction_prompt.md"):
    """
    Load the extraction prompt from a markdown file
    """
    try:
        with open(prompt_file_path, 'r', encoding='utf-8') as f:
            content = f.read()
        # Remove the markdown header and return just the prompt content
        # Find the first line that starts with "You are an expert"
        lines = content.split('\n')
        prompt_start = 0
        for i, line in enumerate(lines):
            if line.startswith("You are an expert"):
                prompt_start = i
                break
        
        prompt_text = '\n'.join(lines[prompt_start:])
        return prompt_text.strip()
    except FileNotFoundError:
        logging.error(f"Prompt file not found: {prompt_file_path}")
        raise
    except Exception as e:
        logging.error(f"Error loading prompt file: {e}")
        raise

def process_pdf_with_gemini(pdf_path, client, model="gemini-flash-latest"):
    """
    Process a single PDF with Gemini API and extract structured data
    """
    try:
        logging.info(f"Processing {pdf_path.name}")
        
        # Load the extraction prompt from file
        prompt_text = load_extraction_prompt()
        
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
                    types.Part.from_text(text=prompt_text),
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
                        description="A summary list of all equipment units. Create ONE array item per equipment group/row as it appears in the source permit. Do NOT merge similar equipment.",
                        items=genai.types.Schema(
                            type=genai.types.Type.OBJECT,
                            required=["type", "referenceNos", "description", "ratedCapacity", "numberOfUnits"],
                            properties={
                                "type": genai.types.Schema(type=genai.types.Type.STRING, description="Equipment type taxonomy - must be one of the four specified categories.", enum=["Constructed", "Modified", "Previously Permitted", "Exempt"]),
                                "referenceNos": genai.types.Schema(type=genai.types.Type.STRING, description="The reference number(s) for the equipment EXACTLY as written in the source document (e.g., 'G-1 to G-8', 'ENG161 – ENG175', 'CT01 through CT11'). Do NOT modify or simplify."),
                                "description": genai.types.Schema(type=genai.types.Type.STRING, description="A concise description of the equipment, including make, model, and primary function (e.g., 'Caterpillar Model 3512 Diesel Generator', 'MTU 20V4000G83L 6 ECT emergency diesel engine gen-sets', 'SPX Marley Cooling Towers')."),
                                "manufacturer": genai.types.Schema(type=genai.types.Type.STRING, description="The manufacturer name (e.g., 'Caterpillar', 'Cummins', 'MTU', 'Clarke', 'Kohler'). Null if not explicitly stated.", nullable=True),
                                "ratedCapacity": genai.types.Schema(type=genai.types.Type.STRING, description="The rated capacity of a single equipment unit as written in the document, including units (e.g., '1,135 kW', '2,500 ekW 3,633 bhp (each)', '2,400 gpm (each)')."),
                                "numberOfUnits": genai.types.Schema(type=genai.types.Type.NUMBER, description="The integer count of individual equipment units in this group (e.g., for 'Forty (40) generators', this value would be 40)."),
                                "fuelType": genai.types.Schema(type=genai.types.Type.STRING, description="The type of fuel used by the equipment. Must be one of the specified values or null.", enum=["Diesel", "Gas", "Dual Fuel"], nullable=True),
                                "isEmergency": genai.types.Schema(type=genai.types.Type.BOOLEAN, description="Set to true if the equipment is designated for emergency, standby, EP, or black start purposes."),
                                "isPeakLoad": genai.types.Schema(type=genai.types.Type.BOOLEAN, description="Set to true if the equipment is designated for peak load, peak shaving, demand response, ELRP, capacity bidding, or similar peak-demand programs. Can be true even if isEmergency is also true."),
                                "electricalCapacity_kW_perUnit": genai.types.Schema(type=genai.types.Type.NUMBER, description="Electrical capacity in kilowatts (kW or ekW) for a SINGLE unit as a number. Null if not specified or not applicable. Use 0 only if explicitly stated as zero.", nullable=True),
                                "electricalCapacity_kW_total": genai.types.Schema(type=genai.types.Type.NUMBER, description="TOTAL combined electrical capacity in kilowatts (kW or ekW) for all units in this group as a number. For multiple units, this is numberOfUnits × per-unit capacity. Null if not specified or not applicable. Use 0 only if explicitly stated as zero.", nullable=True),
                                "mechanicalCapacity_bhp_perUnit": genai.types.Schema(type=genai.types.Type.NUMBER, description="Mechanical capacity in horsepower (HP or bhp) for a SINGLE unit as a number. Null if not specified or not applicable. Use 0 only if explicitly stated as zero.", nullable=True),
                                "mechanicalCapacity_bhp_total": genai.types.Schema(type=genai.types.Type.NUMBER, description="TOTAL combined mechanical capacity in horsepower (HP or bhp) for all units in this group as a number. For multiple units, this is numberOfUnits × per-unit capacity. Null if not specified or not applicable. Use 0 only if explicitly stated as zero.", nullable=True),
                                "gasUsage_MMBTUhr_perUnit": genai.types.Schema(type=genai.types.Type.NUMBER, description="For gas-fired equipment, the heat input rate in MMBTU/hr for a SINGLE unit as a number. Null if not applicable or not specified. Use 0 only if explicitly stated as zero.", nullable=True),
                                "controls": genai.types.Schema(type=genai.types.Type.STRING, description="Inherent engine design features and good operating practices (e.g., 'electronic fuel injection, turbocharged engine, and aftercooler', 'good combustion practices')."),
                                "addOnControlTechnology": genai.types.Schema(type=genai.types.Type.STRING, description="External emission reduction equipment (e.g., 'SCR - Steuler CERNOX', 'Catalyzed Diesel Particulate Filter (cDPF)'). Use 'None' if no external device is mentioned."),
                                "originalPermitDate": genai.types.Schema(type=genai.types.Type.STRING, description="The original permit date for this specific equipment, if explicitly stated and different from the main permit issuance date (YYYY-MM-DD).", format="date", nullable=True),
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
                                    description="A list of exact 'referenceNos' strings from the equipmentSummary this limit applies to, enabling direct programmatic matching. Must match verbatim.",
                                    items=genai.types.Schema(type=genai.types.Type.STRING)
                                ),
                                "limitDetails": genai.types.Schema(type=genai.types.Type.STRING, description="The full, descriptive text of the operational limit, including values, units, conditions, calculation periods, and all granular details. This is the source of truth."),
                                "structuredData": genai.types.Schema(
                                    type=genai.types.Type.OBJECT,
                                    description="Structured extraction of key numeric and categorical data from the limit. Contents vary by category. Null if not applicable.",
                                    nullable=True,
                                    properties={
                                        "calculationMethod": genai.types.Schema(
                                            type=genai.types.Type.STRING,
                                            description="For 'Hours of Operation Limits' only: How the hour limit is calculated.",
                                            enum=["Calendar Year", "Rolling 12-Month", "Per Event", "Daily", "Monthly", "Other"],
                                            nullable=True
                                        ),
                                        "hourLimitPerUnit": genai.types.Schema(
                                            type=genai.types.Type.NUMBER,
                                            description="For 'Hours of Operation Limits' only: Numeric hour limit per individual unit (e.g., 240 for '240 hours per year').",
                                            nullable=True
                                        ),
                                        "hourLimitCombined": genai.types.Schema(
                                            type=genai.types.Type.NUMBER,
                                            description="For 'Hours of Operation Limits' only: Numeric hour limit for all units combined or facility-wide.",
                                            nullable=True
                                        ),
                                        "astmSpecification": genai.types.Schema(
                                            type=genai.types.Type.STRING,
                                            description="For 'Fuel Limits & Specifications' only: ASTM fuel specification (e.g., 'ASTM D975 S15', 'ASTM D975 Grades 1-D or 2-D').",
                                            nullable=True
                                        ),
                                        "maxSulfurContent_percent": genai.types.Schema(
                                            type=genai.types.Type.NUMBER,
                                            description="For 'Fuel Limits & Specifications' only: Maximum sulfur content as percentage (e.g., 0.0015 for 15 ppm ULSD).",
                                            nullable=True
                                        ),
                                        "fuelThroughputLimit_gallons": genai.types.Schema(
                                            type=genai.types.Type.NUMBER,
                                            description="For 'Fuel Limits & Specifications' only: Annual fuel throughput limit in gallons per year.",
                                            nullable=True
                                        ),
                                        "certificationRequired": genai.types.Schema(
                                            type=genai.types.Type.BOOLEAN,
                                            description="For 'Fuel Limits & Specifications' only: True if fuel supplier certification is required for each shipment.",
                                            nullable=True
                                        ),
                                    }
                                ),
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
                                    description="A list of exact 'referenceNos' strings from the equipmentSummary this limit applies to, enabling direct programmatic matching. Must match verbatim.",
                                    items=genai.types.Schema(type=genai.types.Type.STRING)
                                ),
                                "pollutant": genai.types.Schema(type=genai.types.Type.STRING, description="The pollutant(s) being limited (e.g., 'PM-10', 'PM10', 'PM2.5', 'Nitrogen Oxides (as NO2)', 'NOx', 'Carbon Monoxide', 'CO', 'Volatile Organic Compounds', 'VOC', 'Sulfur Dioxide', 'SO2', 'Opacity')."),
                                "limitValue": genai.types.Schema(type=genai.types.Type.NUMBER, description="The numeric limit value as a number (e.g., 1.2, 96.03, 10). For Visible Emissions with conditions, use the primary limit value."),
                                "limitUnit": genai.types.Schema(type=genai.types.Type.STRING, description="The standardized unit of the limit value. Must use ONLY: 'lb/hr', 'tons/yr', 'g/kW-hr', 'lb/kW-hr', 'lb/gal', 'percent opacity', 'ppm', or 'g/dscm'.", enum=["lb/hr", "tons/yr", "g/kW-hr", "lb/kW-hr", "lb/gal", "percent opacity", "ppm", "g/dscm"]),
                                "conditions": genai.types.Schema(type=genai.types.Type.STRING, description="Any specific conditions or context for this limit (e.g., 'Uncontrolled by SCR', 'During startup and shutdown', 'Calculated monthly as consecutive 12-month period', 'except during one 6-minute period not exceeding 20%').", nullable=True),
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
    Retries with gemini-2.5-pro if initial extraction fails
    """
    # First attempt with the specified model
    extracted_data, json_filename = process_pdf_with_gemini(pdf_path, client, model)
    
    # If failed and we're using flash, retry with pro model
    if not extracted_data and model == "gemini-flash-latest":
        extracted_data, json_filename = process_pdf_with_gemini(pdf_path, client, "gemini-2.0-flash")
    
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

def process_all_pdfs(raw_pdfs_dir='raw_pdfs', output_dir='extracted_data'):
    """
    Process all PDFs in year-based subdirectories
    
    Args:
        raw_pdfs_dir: Directory containing year-based PDF folders (default: 'raw_pdfs')
        output_dir: Directory where extracted JSON files will be saved (default: 'extracted_data')
    """
    # Initialize the Gemini client
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        print("Error: GEMINI_API_KEY environment variable not set!")
        return
    client = genai.Client(api_key=api_key)
    
    # Directory containing year-based PDF folders
    raw_pdfs_base = Path(raw_pdfs_dir)
    if not raw_pdfs_base.exists():
        print(f"Error: {raw_pdfs_base} directory not found!")
        return
    
    # Get all year subdirectories
    year_dirs = sorted([d for d in raw_pdfs_base.iterdir() if d.is_dir() and d.name.isdigit()])
    if not year_dirs:
        print(f"No year subdirectories found in {raw_pdfs_base}")
        return
    
    print(f"Input directory: {raw_pdfs_base}")
    print(f"Output directory: {output_dir}")
    print(f"Found {len(year_dirs)} year directories: {[d.name for d in year_dirs]}")
    
    # Create base output directory
    json_data_base = Path(output_dir)
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
    parser = argparse.ArgumentParser(
        description='Extract structured data from air permit PDFs using Gemini AI',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog='''
Examples:
  # Process PDFs from default directories
  python extraction_sync.py
  
  # Specify custom input and output directories
  python extraction_sync.py --input raw_pdfs --output extracted_data
  
  # Process from custom directories
  python extraction_sync.py --input my_pdfs --output my_output
        '''
    )
    
    parser.add_argument(
        '--input',
        type=str,
        default='raw_pdfs',
        help='Directory containing year-based PDF folders (default: raw_pdfs)'
    )
    
    parser.add_argument(
        '--output',
        type=str,
        default='extracted_data',
        help='Directory where extracted JSON files will be saved (default: extracted_data)'
    )
    
    args = parser.parse_args()
    
    process_all_pdfs(raw_pdfs_dir=args.input, output_dir=args.output)