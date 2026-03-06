from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model
from django.utils import timezone
from datetime import timedelta
from services.cflows.models import (
    Organization, UserProfile, Team, Workflow, WorkflowStep, WorkflowTransition,
    WorkItem, WorkItemHistory, JobType, TeamBooking, CalendarEvent
)

User = get_user_model()


class Command(BaseCommand):
    help = 'Create sample data for CFlows - demonstrates car dealership workflow'

    def add_arguments(self, parser):
        parser.add_argument('--org-name', type=str, default='Demo Car Dealership',
                          help='Organization name to create')
        parser.add_argument('--admin-username', type=str, default='admin',
                          help='Admin username to create/use')

    def handle(self, *args, **options):
        org_name = options['org_name']
        admin_username = options['admin_username']
        
        self.stdout.write(f"Creating CFlows sample data for '{org_name}'...")
        
        # Create or get organization
        org, created = Organization.objects.get_or_create(
            name=org_name,
            defaults={
                'slug': org_name.lower().replace(' ', '-'),
                'description': 'A sample car dealership demonstrating CFlows workflow management',
                'time_format_24h': False,  # Use 12-hour format for dealership
            }
        )
        if created:
            self.stdout.write(f"✓ Created organization: {org.name}")
        else:
            self.stdout.write(f"✓ Using existing organization: {org.name}")
        
        # Create or get admin user
        admin_user, created = User.objects.get_or_create(
            username=admin_username,
            defaults={
                'email': f'{admin_username}@{org.slug}.com',
                'first_name': 'Admin',
                'last_name': 'User',
                'is_staff': True,
                'is_superuser': True,
            }
        )
        if created:
            admin_user.set_password('admin123')
            admin_user.save()
            self.stdout.write(f"✓ Created admin user: {admin_user.username} (password: admin123)")
        else:
            self.stdout.write(f"✓ Using existing admin user: {admin_user.username}")
        
        # Create admin profile
        admin_profile, created = UserProfile.objects.get_or_create(
            user=admin_user,
            organization=org,
            defaults={
                'title': 'General Manager',
                'location': 'Main Office',
                'timezone': 'America/New_York',
                'bio': 'Dealership administrator and workflow manager',
                'is_organization_admin': True,
                'has_staff_panel_access': True,
            }
        )
        if created:
            self.stdout.write(f"✓ Created admin profile")
        
        # Create sample users
        sample_users = [
            ('sales_manager', 'Sales', 'Manager', 'Sales Manager', 'Sales Floor'),
            ('test_tech', 'Test', 'Technician', 'Test Technician', 'Service Bay'),
            ('mechanic1', 'Mike', 'Mechanic', 'Senior Mechanic', 'Repair Shop'),
            ('detailer', 'Sarah', 'Detailer', 'Detailing Specialist', 'Detail Shop'),
            ('photographer', 'Photo', 'Pro', 'Vehicle Photographer', 'Photo Studio'),
        ]
        
        user_profiles = {}
        for username, first_name, last_name, title, location in sample_users:
            user, created = User.objects.get_or_create(
                username=username,
                defaults={
                    'email': f'{username}@{org.slug}.com',
                    'first_name': first_name,
                    'last_name': last_name,
                }
            )
            if created:
                user.set_password('password123')
                user.save()
                self.stdout.write(f"✓ Created user: {user.username}")
            
            profile, created = UserProfile.objects.get_or_create(
                user=user,
                organization=org,
                defaults={
                    'title': title,
                    'location': location,
                    'timezone': 'America/New_York',
                }
            )
            user_profiles[username] = profile
        
        # Create teams
        teams_data = [
            ('Sales Team', 'Vehicle sales and customer service', 2, ['sales_manager']),
            ('Testing Team', 'Vehicle inspection and testing', 1, ['test_tech']),
            ('Repair Team', 'Vehicle maintenance and repairs', 3, ['mechanic1']),
            ('Detailing Team', 'Vehicle cleaning and detailing', 2, ['detailer']),
            ('Photography Team', 'Vehicle photography for listings', 1, ['photographer']),
        ]
        
        teams = {}
        for team_name, description, capacity, member_usernames in teams_data:
            team, created = Team.objects.get_or_create(
                organization=org,
                name=team_name,
                defaults={
                    'description': description,
                    'default_capacity': capacity,
                }
            )
            if created:
                self.stdout.write(f"✓ Created team: {team.name}")
            
            # Add members
            for username in member_usernames:
                if username in user_profiles:
                    team.members.add(user_profiles[username])
            
            teams[team_name] = team
        
        # Create job types
        job_types_data = [
            ('Vehicle Inspection', 'Complete vehicle inspection', 2.0, '#3B82F6'),
            ('Mechanical Repair', 'Mechanical repairs and maintenance', 4.0, '#EF4444'),
            ('Body Work', 'Body repairs and painting', 6.0, '#F59E0B'),
            ('Detailing', 'Interior and exterior cleaning', 3.0, '#10B981'),
            ('Photography', 'Vehicle photography session', 1.0, '#8B5CF6'),
        ]
        
        job_types = {}
        for name, description, duration, color in job_types_data:
            job_type, created = JobType.objects.get_or_create(
                organization=org,
                name=name,
                defaults={
                    'description': description,
                    'default_duration_hours': duration,
                    'color': color,
                }
            )
            if created:
                self.stdout.write(f"✓ Created job type: {job_type.name}")
            job_types[name] = job_type
        
        # Create vehicle workflow
        workflow, created = Workflow.objects.get_or_create(
            organization=org,
            name='Vehicle Processing Workflow',
            defaults={
                'description': 'Complete vehicle processing from acquisition to sale',
                'created_by': admin_profile,
                'owner_team': teams['Sales Team'],
            }
        )
        if created:
            self.stdout.write(f"✓ Created workflow: {workflow.name}")
        
        # Create workflow steps
        steps_data = [
            ('Vehicle Intake', 'Initial vehicle intake and documentation', 1, 'Sales Team', False, False),
            ('Test & Inspect', 'Complete vehicle testing and inspection', 2, 'Testing Team', True, False),
            ('Repair Assessment', 'Assess required repairs', 3, 'Repair Team', False, False),
            ('Mechanical Repairs', 'Complete mechanical repairs', 4, 'Repair Team', True, False),
            ('Body Work', 'Complete body work and painting', 5, 'Repair Team', True, False),
            ('Final Inspection', 'Final quality inspection', 6, 'Testing Team', True, False),
            ('Detailing', 'Complete vehicle detailing', 7, 'Detailing Team', True, False),
            ('Photography', 'Professional vehicle photography', 8, 'Photography Team', True, False),
            ('Listing Created', 'Vehicle listed for sale', 9, 'Sales Team', False, False),
            ('Sold', 'Vehicle sold to customer', 10, 'Sales Team', False, True),
        ]
        
        steps = {}
        for step_name, description, order, team_name, requires_booking, is_terminal in steps_data:
            step, created = WorkflowStep.objects.get_or_create(
                workflow=workflow,
                name=step_name,
                defaults={
                    'description': description,
                    'order': order,
                    'assigned_team': teams.get(team_name),
                    'requires_booking': requires_booking,
                    'is_terminal': is_terminal,
                    'estimated_duration_hours': 2.0 if requires_booking else None,
                    'data_schema': {
                        'type': 'object',
                        'properties': {
                            'notes': {'type': 'string', 'title': 'Notes'},
                            'photos': {'type': 'array', 'title': 'Photos', 'items': {'type': 'string'}},
                        }
                    }
                }
            )
            if created:
                self.stdout.write(f"✓ Created workflow step: {step.name}")
            steps[step_name] = step
        
        # Create workflow transitions (sequential flow with some branching)
        transitions_data = [
            ('Vehicle Intake', 'Test & Inspect', ''),
            ('Test & Inspect', 'Repair Assessment', 'Needs Repair'),
            ('Test & Inspect', 'Final Inspection', 'No Repairs Needed'),
            ('Repair Assessment', 'Mechanical Repairs', 'Mechanical Issues'),
            ('Repair Assessment', 'Body Work', 'Body Issues'),
            ('Repair Assessment', 'Final Inspection', 'Minor Issues Only'),
            ('Mechanical Repairs', 'Final Inspection', 'Repairs Complete'),
            ('Body Work', 'Final Inspection', 'Body Work Complete'),
            ('Final Inspection', 'Detailing', 'Passed'),
            ('Final Inspection', 'Repair Assessment', 'Failed - Needs More Work'),
            ('Detailing', 'Photography', ''),
            ('Photography', 'Listing Created', ''),
            ('Listing Created', 'Sold', ''),
        ]
        
        for from_step_name, to_step_name, label in transitions_data:
            if from_step_name in steps and to_step_name in steps:
                transition, created = WorkflowTransition.objects.get_or_create(
                    from_step=steps[from_step_name],
                    to_step=steps[to_step_name],
                    defaults={'label': label}
                )
                if created:
                    self.stdout.write(f"✓ Created transition: {from_step_name} → {to_step_name}")
        
        # Create sample work items (vehicles)
        sample_vehicles = [
            ('2020 Honda Civic LX', 'Blue sedan, 45,000 miles, clean title', 'Vehicle Intake'),
            ('2018 Ford F-150 XLT', 'White pickup truck, 62,000 miles, minor dents', 'Test & Inspect'),
            ('2019 Toyota Camry SE', 'Silver sedan, 38,000 miles, excellent condition', 'Detailing'),
            ('2021 BMW X3 xDrive', 'Black SUV, 25,000 miles, needs mechanical work', 'Mechanical Repairs'),
            ('2017 Chevrolet Malibu', 'Gray sedan, 78,000 miles, ready for photos', 'Photography'),
        ]
        
        work_items = []
        for title, description, current_step_name in sample_vehicles:
            work_item, created = WorkItem.objects.get_or_create(
                workflow=workflow,
                title=title,
                defaults={
                    'description': description,
                    'current_step': steps[current_step_name],
                    'created_by': admin_profile,
                    'current_assignee': user_profiles.get('sales_manager') if current_step_name == 'Vehicle Intake' else None,
                    'data': {
                        'vin': f'1HGBH41JXMN{str(hash(title))[:6].upper()}',
                        'year': int(title.split()[0]),
                        'make': title.split()[1],
                        'model': ' '.join(title.split()[2:-1]),
                        'mileage': description.split('miles')[0].split()[-1].replace(',', '') if 'miles' in description else '50000',
                        'condition': 'good',
                        'acquisition_price': 15000 + hash(title) % 10000,
                        'target_price': 18000 + hash(title) % 12000,
                    }
                }
            )
            if created:
                self.stdout.write(f"✓ Created work item: {work_item.title}")
                
                # Create some history for the work item
                if current_step_name != 'Vehicle Intake':
                    history = WorkItemHistory.objects.create(
                        work_item=work_item,
                        from_step=None,
                        to_step=steps['Vehicle Intake'],
                        changed_by=admin_profile,
                        notes='Vehicle acquired and entered into system',
                        data_snapshot=work_item.data
                    )
            
            work_items.append(work_item)
        
        # Create some sample bookings
        now = timezone.now()
        sample_bookings = [
            ('Vehicle Inspection - Honda Civic', 'Testing Team', 'Vehicle Inspection', 1, 2.0, now + timedelta(hours=2)),
            ('Repair Work - Ford F-150', 'Repair Team', 'Mechanical Repair', 2, 4.0, now + timedelta(days=1)),
            ('Detail Work - Toyota Camry', 'Detailing Team', 'Detailing', 1, 3.0, now + timedelta(days=2)),
            ('Photo Session - Chevrolet', 'Photography Team', 'Photography', 1, 1.0, now + timedelta(days=3)),
        ]
        
        for title, team_name, job_type_name, members, duration, start_time in sample_bookings:
            booking, created = TeamBooking.objects.get_or_create(
                title=title,
                team=teams[team_name],
                defaults={
                    'job_type': job_types[job_type_name],
                    'description': f'Scheduled {job_type_name.lower()} work',
                    'start_time': start_time,
                    'end_time': start_time + timedelta(hours=duration),
                    'required_members': members,
                    'booked_by': admin_profile,
                    'work_item': work_items[0] if work_items else None,  # Link to first work item
                }
            )
            if created:
                self.stdout.write(f"✓ Created booking: {booking.title}")
        
        # Create sample calendar events
        sample_events = [
            ('Team Meeting - Sales', 'Weekly sales team meeting', 'team', now + timedelta(days=7), 1.0, teams['Sales Team']),
            ('Staff Training', 'New workflow training session', 'organization', now + timedelta(days=14), 2.0, None),
            ('Inventory Review', 'Monthly inventory and process review', 'organization', now + timedelta(days=21), 3.0, None),
        ]
        
        for title, description, event_type, start_time, duration, related_team in sample_events:
            event, created = CalendarEvent.objects.get_or_create(
                title=title,
                organization=org,
                defaults={
                    'description': description,
                    'event_type': event_type,
                    'start_time': start_time,
                    'end_time': start_time + timedelta(hours=duration),
                    'created_by': admin_profile,
                    'related_team': related_team,
                    'color': '#6366F1',
                }
            )
            if created:
                self.stdout.write(f"✓ Created calendar event: {event.title}")
        
        self.stdout.write(
            self.style.SUCCESS(
                f'\n🎉 Successfully created CFlows sample data for "{org.name}"!\n\n'
                f'You can now:\n'
                f'• Visit /services/cflows/ to see the dashboard\n'
                f'• Login with username: {admin_username} / password: admin123\n'
                f'• Explore the vehicle processing workflow\n'
                f'• See work items in various stages\n'
                f'• View team bookings and calendar events\n\n'
                f'The sample demonstrates a car dealership workflow where vehicles move through:\n'
                f'Intake → Testing → Repair → Detailing → Photography → Listing → Sale\n'
            )
        )
