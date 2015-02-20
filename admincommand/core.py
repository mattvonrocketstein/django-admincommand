import threading
from StringIO import StringIO

from django.conf import settings
from django.core import management
from django.core.management import get_commands
from django.core.management import load_command_class
from django.utils.importlib import import_module
from django.core.management.base import BaseCommand
from django.contrib.auth.models import User
from async import schedule

from admincommand.models import AdminCommand


# Cache variable to store runnable commands configuration
_command_configs = {}


def get_admin_commands():
    if not _command_configs:
        for app_module_path in settings.INSTALLED_APPS:
            try:
                admin_commands_path = '%s.admincommands' % app_module_path
                module = import_module(admin_commands_path)
            except ImportError:
                pass
            else:
                configs = dir(module)
                for config_name in configs:
                    AdminCommandClass = getattr(module, config_name)
                    if (isinstance(AdminCommandClass, type)
                        and AdminCommandClass is not AdminCommand
                        and issubclass(AdminCommandClass, AdminCommand)):
                        command_config = AdminCommandClass()
                        _command_configs[command_config.url_name()] = command_config
    return _command_configs


def get_command(name):
    # this is a copy pasted from django.core.management.call_command
    app_name = get_commands()[name]
    if isinstance(app_name, BaseCommand):
        # If the command is already loaded, use it directly.
        klass = app_name
    else:
        klass = load_command_class(app_name, name)
    return klass


def call_command(command_name, user_pk, args=None, kwargs=None):
    """Call command and store output"""
    user = User.objects.get(pk=user_pk)
    kwargs = kwargs if kwargs else {}
    args = args if args else []
    output = StringIO()
    kwargs['stdout'] = output
    management.call_command(command_name, *args, **kwargs)
    return output.getvalue()

def run_command(command_config, cleaned_data, user):
    if hasattr(command_config, 'get_command_arguments'):
        args, kwargs = command_config.get_command_arguments(cleaned_data)
    else:
        args, kwargs = list(), dict()
    if command_config.asynchronous:
        task = schedule(call_command, [command_config.command_name(), user.pk, args, kwargs])
        return task
    else:
        # Change stdout to a StringIO to be able to retrieve output and
        # display it to the user
        output = StringIO()
        kwargs['stdout'] = output
        call_command = lambda: management.call_command(command_config.command_name(), *args, **kwargs)
        if command_config.thread:
            # AdminCommand.thread is (undocumented) support for calling management commands
            # from a threaded context.  This is usually a bad idea, but due to post-save signals
            # etc it may be the only option in certain circumstances (for example, see this
            # old ticket here https://code.djangoproject.com/ticket/8399)
            thread = threading.Thread(target=call_command)
            thread.start()
            thread.join()
            return "(executed in a thread)\n" + output.getvalue()
        else:
            call_command()
            return output.getvalue()
