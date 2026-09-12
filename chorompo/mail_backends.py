from django.core.mail.backends.console import EmailBackend as DjangoConsoleEmailBackend


class ReadableConsoleEmailBackend(DjangoConsoleEmailBackend):
    """Display the original text so development links can be copied intact."""

    def write_message(self, message):
        self.stream.write(f"Assunto: {message.subject}\n")
        self.stream.write(f"De: {message.from_email}\n")
        self.stream.write(f"Para: {', '.join(message.to)}\n\n")
        self.stream.write(message.body)
        self.stream.write("\n" + "-" * 79 + "\n")
