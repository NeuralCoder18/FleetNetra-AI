
import os, json
try:
    from google import genai
except Exception:
    genai=None

def generate_report(data):
    key=os.getenv("GEMINI_API_KEY")
    if not key or genai is None:
        return fallback(data)
    model=os.getenv("GEMINI_MODEL","gemini-3.8-flash")
    client=genai.Client(api_key=key)
    prompt=f"""You are an urban traffic authority intelligence analyst.
Create a decision-ready road and mobility report from the structured platform data below.
Rules:
- Use ONLY supplied facts; do not invent numbers, roads, budgets, causes, or locations.
- Medium length: about 450-650 words, not a one-paragraph summary.
- Include: Executive Summary, Key Road Findings, Safety/Traffic Implications, Priority Actions, Maintenance/Monitoring Recommendations.
- Explain that AI detections are observations requiring appropriate authority verification before physical work.
- If data is simulated, explicitly say so.
DATA:
{json.dumps(data, default=str)}"""
    try:
        response=client.models.generate_content(model=model,contents=prompt)
        return response.text or fallback(data)
    except Exception as e:
        return fallback(data)+f"\n\n[Gemini unavailable: {type(e).__name__}]"

def fallback(data):
    ds=data.get("detections",[])
    high=sum(1 for x in ds if x.get("severity")=="HIGH")
    roads={}
    for x in ds:
        roads[x.get("road","Unknown")]=roads.get(x.get("road","Unknown"),0)+1
    top=", ".join(f"{k} ({v})" for k,v in sorted(roads.items(),key=lambda x:-x[1])[:5]) or "No road detections recorded."
    return f"""Executive Summary

The Urban Intelligence Platform currently contains {len(ds)} stored AI road-defect observations, including {high} marked high severity. The observations are designed to help a traffic authority focus inspection and maintenance resources on corridors showing repeated or high-impact road problems.

Key Road Findings

The most represented roads in the stored detection data are: {top}. Each AI observation includes a location, time, bus/camera source and confidence value where available. Repeated observations from different buses can be aggregated into a single road event to reduce duplicate tickets.

Safety and Traffic Implications

Road defects can contribute to slower traffic, uncomfortable bus movement and increased risk for road users. The platform can combine road-condition signals with fleet telemetry and community reports to identify corridors that deserve closer inspection. These AI observations should be treated as decision-support evidence rather than an automatic repair order.

Priority Actions

Traffic authorities should first inspect high-severity or repeatedly observed defects, verify the physical condition on site, and then assign a maintenance priority. GIS visualization can help compare affected corridors and coordinate field teams.

Maintenance and Monitoring Recommendations

After verification, create a work order and monitor its status through completion. Continue collecting observations from buses so that repaired locations can be checked for recurrence. Community submissions can provide an additional signal between fleet passes.

Note: This report is generated from currently stored platform data. No unsupported statistics or claims have been added."""
