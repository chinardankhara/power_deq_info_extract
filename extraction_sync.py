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

def process_pdf_with_gemini(pdf_path, client, model="gemini-2.5-flash"):
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
                        text="""Please extract all the key information from this air permit document according to the provided schema. 
                        Focus on identifying:
                        - Data center/facility name
                        - Permit issuance date
                        - Registration number
                        - Location details
                        - All equipment (generators, cooling towers, etc.) with their specifications
                        - Operational limits and restrictions
                        - Emission limits for all pollutants
                        
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
                                    description="Whether the equipment is 'Constructed' or 'Previously Permitted'.",
                                    enum=["Constructed", "Previously Permitted"],
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
                                "controls": genai.types.Schema(
                                    type=genai.types.Type.STRING,
                                    description="Any specified control devices or methods, if explicitly mentioned (e.g., 'SCR and Catalyzed Diesel Particulate Filter (CDPF)', 'Electronic fuel injection and aftercooler'). If no specific controls are mentioned, it can be 'None' or left null.",
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
            
            # Save immediately
            output_dir = Path('extracted_data')
            output_dir.mkdir(exist_ok=True)
            json_path = output_dir / json_filename
            
            with open(json_path, 'w', encoding='utf-8') as f:
                json.dump(extracted_data, f, indent=2, ensure_ascii=False)
            
            print(f"✓ SAVED: {json_filename}")
            
            # Show progress
            completed_files = len(list(output_dir.glob("*.json")))
            print(f"Progress: {completed_files} files completed")
            
            return extracted_data, json_filename
            
        except json.JSONDecodeError as e:
            logging.error(f"Failed to parse JSON response for {pdf_path.name}: {e}")
            return None, None
            
    except Exception as e:
        logging.error(f"Error processing {pdf_path.name}: {e}")
        return None, None

def process_all_pdfs():
    """
    Process all PDFs in the raw_pdfs directory synchronously
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
    
    # Directory containing raw PDFs
    raw_pdfs_dir = Path('retries')
    
    if not raw_pdfs_dir.exists():
        print(f"Error: {raw_pdfs_dir} directory not found!")
        return
    
    # Get all PDF files
    pdf_files = list(raw_pdfs_dir.glob("*.pdf"))
    
    if not pdf_files:
        print(f"No PDF files found in {raw_pdfs_dir}")
        return
    
    print(f"Found {len(pdf_files)} PDF files to process")
    print(f"Processing synchronously (one at a time)")
    
    # Create output directory for extracted data
    output_dir = Path('extracted_data')
    output_dir.mkdir(exist_ok=True)
    
    # Process each PDF one by one
    all_extracted_data = []
    successful_extractions = 0
    failed_extractions = 0
    
    for i, pdf_path in enumerate(pdf_files, 1):
        print(f"\n[{i}/{len(pdf_files)}] Processing: {pdf_path.name}")
        start_time = time.time()
        
        # Extract data from PDF
        extracted_data, json_filename = process_pdf_with_gemini(pdf_path, client)
        
        elapsed_time = time.time() - start_time
        
        if extracted_data and json_filename:
            all_extracted_data.append(extracted_data)
            successful_extractions += 1
            print(f"✓ Completed in {elapsed_time:.1f}s")
        else:
            print(f"✗ Failed: {pdf_path.name}")
            failed_extractions += 1
        
        # Small delay between requests to be respectful to the API
        if i < len(pdf_files):
            time.sleep(1)
    
    # Save combined results
    if all_extracted_data:
        # Save as JSON
        combined_json_path = output_dir / 'all_extracted_data.json'
        with open(combined_json_path, 'w', encoding='utf-8') as f:
            json.dump(all_extracted_data, f, indent=2, ensure_ascii=False)
        
        # Convert to DataFrame and save as CSV for easier analysis
        try:
            # Flatten the data for CSV export
            flattened_data = []
            for data in all_extracted_data:
                base_info = {
                    'source_file': data.get('source_file'),
                    'dataCenterName': data.get('dataCenterName'),
                    'permitIssuanceDate': data.get('permitIssuanceDate'),
                    'registrationNumber': data.get('registrationNumber'),
                    'location': data.get('location'),
                    'equipment_count': len(data.get('equipmentSummary', [])),
                    'operational_limits_count': len(data.get('operationalLimits', [])),
                    'emission_limits_count': len(data.get('emissionLimits', []))
                }
                flattened_data.append(base_info)
            
            df = pd.DataFrame(flattened_data)
            csv_path = output_dir / 'extracted_data_summary.csv'
            df.to_csv(csv_path, index=False)
            
            print(f"\n✓ Combined data saved to {combined_json_path}")
            print(f"✓ Summary CSV saved to {csv_path}")
            
        except Exception as e:
            logging.error(f"Error creating CSV summary: {e}")
    
    # Print final summary
    print(f"\n=== Processing Summary ===")
    print(f"Total PDFs: {len(pdf_files)}")
    print(f"Successfully processed: {successful_extractions}")
    print(f"Failed: {failed_extractions}")
    print(f"Output directory: {output_dir.absolute()}")
    
    # Show some example files created
    json_files = list(output_dir.glob("*.json"))
    individual_files = [f for f in json_files if f.name != 'all_extracted_data.json']
    
    if individual_files:
        print(f"\nIndividual JSON files created:")
        for file in sorted(individual_files)[:10]:  # Show first 10
            print(f"  - {file.name}")
        if len(individual_files) > 10:
            print(f"  ... and {len(individual_files) - 10} more files")

if __name__ == "__main__":
    process_all_pdfs()
