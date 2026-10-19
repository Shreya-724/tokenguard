import asyncio
import signal

from channels.layers import get_channel_layer
from django.core.management.base import BaseCommand, CommandError

from tokenguard.django.feed import run_feed


class Command(BaseCommand):
    help = "Push a stats snapshot to connected dashboards every second."

    def add_arguments(self, parser):
        parser.add_argument("--interval", type=float, default=1.0)
        parser.add_argument("--seconds", type=int, default=60, help="chart window")
        parser.add_argument("--step", type=int, default=1, help="chart bucket size")

    def handle(self, *args, **options):
        layer = get_channel_layer()
        if layer is None:
            raise CommandError("CHANNEL_LAYERS is not configured")
        self.stdout.write("tokenguard feed running (Ctrl+C to stop)")
        try:
            asyncio.run(self._main(layer, options))
        except KeyboardInterrupt:  # Windows has no signal handlers for this
            pass

    async def _main(self, layer, options):
        stop = asyncio.Event()
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                loop.add_signal_handler(sig, stop.set)
            except NotImplementedError:  # Windows: Ctrl+C raises KeyboardInterrupt
                pass
        await run_feed(
            layer,
            interval=options["interval"],
            stop=stop,
            seconds=options["seconds"],
            step=options["step"],
        )
