from django.core.management.base import BaseCommand
from haystack import connections
from patients.models import PatientProfile
import time
import sys

class Command(BaseCommand):
    help = 'Batch index all patients for better performance'
    
    def add_arguments(self, parser):
        parser.add_argument(
            '--batch-size',
            type=int,
            default=1000,
            help='Number of patients per batch (default: 1000)'
        )
        parser.add_argument(
            '--clear-first',
            action='store_true',
            default=True,
            help='Clear existing index before indexing (default: True)'
        )
        parser.add_argument(
            '--no-clear',
            action='store_false',
            dest='clear_first',
            help='Do not clear existing index (add to existing)'
        )
    
    def handle(self, *args, **options):
        batch_size = options['batch_size']
        clear_first = options['clear_first']
        
        # Safety check for batch size
        if batch_size > 5000:
            self.stdout.write(
                self.style.WARNING(
                    f" Batch size {batch_size} may cause memory issues. "
                    "Consider using 1000-2000 for 120k records."
                )
            )
            
            # Ask for confirmation
            confirm = input("Continue anyway? (y/n): ")
            if confirm.lower() != 'y':
                self.stdout.write("Aborted.")
                return
        
        self.stdout.write(f"🚀 Starting batch indexing with {batch_size} patients per batch...")
        
        try:
            # Get backend
            backend = connections['default'].get_backend()
            
            # Clear existing index if requested
            if clear_first:
                self.stdout.write(" Clearing existing index...")
                backend.clear()
                self.stdout.write(" Cleared existing index")
            
            # Get total count with ordering for consistent batches
            total = PatientProfile.objects.filter(active=1).count()
            
            if total == 0:
                self.stdout.write(self.style.WARNING(" No active patients found to index"))
                return
            
            self.stdout.write(f" Total patients to index: {total:,}")
            self.stdout.write("-" * 50)
            
            # Process in batches
            processed = 0
            start_time = time.time()
            errors = 0
            
            for start in range(0, total, batch_size):
                end = min(start + batch_size, total)
                
                try:
                    # Get batch of patients with ordering
                    batch = list(
                        PatientProfile.objects
                        .filter(active=1)
                        .order_by('id')  # Critical for consistent batches
                        .only(
                            'id', 'surname', 'first_name', 'other_name', 
                            'hospital_number', 'phone_number', 'category',
                            'active'
                        )[start:end]
                    )
                    
                    if not batch:
                        continue
                    
                    # Index the batch
                    backend.update(batch)
                    
                    processed += len(batch)
                    elapsed = time.time() - start_time
                    
                    # Progress report
                    percent = (processed / total) * 100
                    rate = processed / elapsed if elapsed > 0 else 0
                    eta = (total - processed) / rate if rate > 0 else 0
                    
                    # Show memory usage 
                    import psutil
                    memory_mb = psutil.Process().memory_info().rss / 1024 / 1024
                    
                    self.stdout.write(
                        f"📦 Batch {start//batch_size + 1:3d}/{(total-1)//batch_size + 1:3d} | "
                        f"Processed {processed:6,}/{total:,} ({percent:4.1f}%) | "
                        f"Speed: {rate:5.0f} rec/sec | "
                        f"RAM: {memory_mb:.0f}MB | "
                        f"ETA: {eta/60:4.1f} min"
                    )
                    
                except Exception as e:
                    errors += 1
                    self.stdout.write(
                        self.style.ERROR(
                            f" Error processing batch {start//batch_size + 1}: {str(e)}"
                        )
                    )
                    
                    # Continuing with next batch instead of failing completely
                    continue
            
            total_time = time.time() - start_time
            
            # Final summary
            self.stdout.write("-" * 50)
            if errors == 0:
                self.stdout.write(
                    self.style.SUCCESS(
                        f" Successfully indexed {processed:,} patients in {total_time/60:.1f} minutes"
                    )
                )
            else:
                self.stdout.write(
                    self.style.WARNING(
                        f"  Indexed {processed:,} patients with {errors} errors in {total_time/60:.1f} minutes"
                    )
                )
                
        except KeyboardInterrupt:
            self.stdout.write("\n" + self.style.WARNING("  Indexing interrupted by user"))
            self.stdout.write(f" Successfully indexed {processed:,} patients before interruption")
            
        except Exception as e:
            self.stdout.write(
                self.style.ERROR(f" Fatal error: {str(e)}")
            )
            sys.exit(1)