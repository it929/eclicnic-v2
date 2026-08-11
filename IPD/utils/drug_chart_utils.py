from datetime import timedelta

def get_all_administered_drugs(patient, start_date, end_date):
    """
    Fetch administered drugs from all 5 transaction models for a given patient and date range.
    If start_date and end_date are None, fetch ALL prescriptions without date filtering.
    """
    all_drugs = []
    
    # Direct imports
    try:
        from IPD_pharm.models import IPDAdministeredDrugs
        from IPD_pharm2.models import IPD2AdministeredDrugs
        from IPD_pharm3.models import IPD3AdministeredDrugs
        from OPD_pharm.models import OPDAdministeredDrugs
        from OPD_pharm2.models import OPD2AdministeredDrugs
        
        stores = [
            ('ipd_pharm1', IPDAdministeredDrugs, 'IPDAdministeredDrugs'),
            ('ipd_pharm2', IPD2AdministeredDrugs, 'IPD2AdministeredDrugs'),
            ('ipd_pharm3', IPD3AdministeredDrugs, 'IPD3AdministeredDrugs'),
            ('opd_pharm1', OPDAdministeredDrugs, 'OPDAdministeredDrugs'),
            ('opd_pharm2', OPD2AdministeredDrugs, 'OPD2AdministeredDrugs'),
        ]
        
        for store_id, model, model_name in stores:
            # Get ALL completed prescriptions for this patient
            drugs = model.objects.filter(
                patient=patient,
                completed=1
            ).select_related('product', 'staff')
            
            print(f"\n📊 {store_id}: Found {drugs.count()} total completed prescriptions")
            
            for drug in drugs:
                # Determine the effective start date
                drug_start_date = drug.start_date if drug.start_date else drug.created_date.date()
                
                # Calculate stop date if duration exists
                drug_stop_date = None
                if drug.duration and drug.duration > 0:
                    drug_stop_date = drug_start_date + timedelta(days=drug.duration)
                
                # ONLY APPLY DATE FILTER if start_date and end_date are provided (not None)
                should_include = True
                
                if start_date is not None and end_date is not None:
                    # Check if this prescription should be included in the date range
                    # A prescription should be shown if its start_date falls within the range OR
                    # if it started before but is still active during the range
                    should_include = False
                    
                    # Case 1: Prescription starts within the selected date range
                    if start_date <= drug_start_date <= end_date:
                        should_include = True
                    
                    # Case 2: Prescription started before the range but is still active
                    elif drug_start_date < start_date:
                        if drug_stop_date is None:
                            # No end date - ongoing prescription
                            should_include = True
                        elif drug_stop_date >= start_date:
                            # Has end date but extends into the range
                            should_include = True
                
                if should_include:
                    all_drugs.append({
                        'id': drug.id,
                        'store_id': store_id,
                        'app_name': model._meta.app_label,
                        'model_name': model_name,
                        'drug_name': drug.item,
                        'dose': drug.dose,
                        'route': drug.route,
                        'frequency': drug.frequency,
                        'quantity': drug.quantity,
                        'UoM': drug.get_UoM_display() if drug.UoM else '',
                        'duration': drug.duration,
                        'notes': drug.notes,
                        'prescribed_by': drug.staff.fullname if drug.staff else 'Unknown',
                        'prescribed_at': drug.created_date,
                        'start_date': drug_start_date,
                        'stop_date': drug_stop_date,
                    })
                    print(f"  ✓ INCLUDED: {drug.item} (Start: {drug_start_date}, Stop: {drug_stop_date})")
                else:
                    print(f"  ✗ EXCLUDED: {drug.item} (Start: {drug_start_date}, Stop: {drug_stop_date}) - Not in range")
                    
    except ImportError as e:
        print(f"Import error: {e}")
    
    print(f"\n{'='*50}")
    print(f"TOTAL prescriptions: {len(all_drugs)}")
    return all_drugs


   
   
