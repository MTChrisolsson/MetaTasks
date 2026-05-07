from django.test import TestCase
from django.contrib.auth import get_user_model
from core.models import Organization
from .models import Project, Task, Milestone


class ProjectModelTest(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username='testuser',
            email='test@example.com',
            password='testpass123'
        )
        self.organization = Organization.objects.create(
            name='Test Org',
            type='business'
        )
        self.project = Project.objects.create(
            organization=self.organization,
            name='Test Project',
            description='A test project',
            created_by=self.user
        )

    def test_project_creation(self):
        self.assertEqual(self.project.name, 'Test Project')
        self.assertEqual(self.project.organization, self.organization)
        self.assertEqual(self.project.status, 'planning')

    def test_project_str(self):
        self.assertEqual(str(self.project), 'Test Project (Test Org)')


class TaskModelTest(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username='testuser',
            email='test@example.com',
            password='testpass123'
        )
        self.organization = Organization.objects.create(
            name='Test Org',
            type='business'
        )
        self.project = Project.objects.create(
            organization=self.organization,
            name='Test Project',
            created_by=self.user
        )
        self.task = Task.objects.create(
            project=self.project,
            title='Test Task',
            description='A test task',
            assigned_to=self.user,
            created_by=self.user
        )

    def test_task_creation(self):
        self.assertEqual(self.task.title, 'Test Task')
        self.assertEqual(self.task.project, self.project)
        self.assertEqual(self.task.status, 'todo')

    def test_task_str(self):
        self.assertEqual(str(self.task), 'Test Task (Test Project)')


class MilestoneModelTest(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username='testuser',
            email='test@example.com',
            password='testpass123'
        )
        self.organization = Organization.objects.create(
            name='Test Org',
            type='business'
        )
        self.project = Project.objects.create(
            organization=self.organization,
            name='Test Project',
            created_by=self.user
        )
        self.milestone = Milestone.objects.create(
            project=self.project,
            title='Test Milestone',
            due_date='2026-12-31',
            created_by=self.user
        )

    def test_milestone_creation(self):
        self.assertEqual(self.milestone.title, 'Test Milestone')
        self.assertEqual(self.milestone.project, self.project)
        self.assertFalse(self.milestone.is_completed)