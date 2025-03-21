from typing import Optional, Literal

import discord
from discord.ext import commands
from discord.ext import tasks
from discord import app_commands

from ..environment import ROLES, START_CHANNEL, GUILD, NOT_BEFORE, CHECK_PERIOD, ONBOARDING_CHANNEL, ONBOARDING_ROLE
from ..log_setup import logger

from .buttons import OnboardingButtons, EntryPointView


class VerificationListener(commands.Cog):
    """
    Give member target roles if member accepts rules screen, check for members that were missed
    """

    def __init__(self, bot: commands.Bot):
        # bot is single server based - for now...
        self.bot = bot
        self.guild: discord.Guild = bot.get_guild(GUILD)
        print(self.guild)
        self.roles = [self.guild.get_role(role) for role in ROLES]
        self.walk_members.start()  # start backup task
        self.onboarding_channel = self.guild.get_channel(ONBOARDING_CHANNEL)
        self.onboarding_role = self.guild.get_role(ONBOARDING_ROLE)

    async def cog_load(self):
        """
        Sends a new start button every time, to ensure that the current button is functional
        """
        await self.onboarding_channel.purge()
        await self.onboarding_channel.send("Klick auf den Button und wähle die Optionen, die auf dich zutreffen.\n"
                                           "Bei Problemen wende dich bitte an die Serverleitung :)",
                                           view=EntryPointView(self.bot, "Freischalten"))

    async def send_onboarding_message(self, member: discord.Member) -> discord.Message:
        return await member.send("Bitte wähle hier aus, was auf dich zutrifft.\n"
                                 "Ignorier diese Nachricht, wenn du dies bereits auf dem Server gemacht hast :)",
                                 view=OnboardingButtons(self.bot))

    @app_commands.command(name="update_base_roles", description="Update your base roles")
    # @app_commands.guild_only
    async def update_base_roles(self,
                                interaction: discord.Interaction,
                                mode: Optional[Literal["silent", "loud"]] = "silent"):
        await interaction.response.send_message(
            "Bitte wähle hier aus, was auf dich zutrifft.\n"
            "Ignorier diese Nachricht, wenn du dies bereits auf dem Server gemacht hast :)",
            view=OnboardingButtons(self.bot),
            ephemeral=mode == "silent"
        )


    @commands.Cog.listener()
    async def on_member_update(self, before_member: discord.Member, after_member: discord.Member):
        """ Give member target roles if member accepts rules screen """

        if after_member.guild.id != GUILD:
            return

        if before_member.pending and not after_member.pending:
            # TODO: maybe merge these two messages together to save api calls and make bot less annoying?
            #  thing why it's two messages:
            #  the first one is personalized the second one is generic and sent to the server too
            await after_member.send(self.get_welcome_text(after_member))

            # send message containing the selection buttons - this is a new message on purpose
            # we can edit this message without losing the greeting text
            await self.send_onboarding_message(after_member)

            # set member in onboarding mode
            # allow only to see the onboarding channel where users are confronted with buttons
            await after_member.add_roles(self.onboarding_role)

    @tasks.loop(minutes=CHECK_PERIOD)
    async def walk_members(self):
        """ Walk all members every n minutes to fix errors that may occur due to downtimes or other errors """
        logger.info("Executing member check")
        i = 0
        j = 0
        async for member in self.guild.fetch_members():
            # check amount of roles,
            # if member is not pending
            # if he joined after a specific date to not verify old members
            if len(member.roles) == 1 and not member.pending and member.joined_at.replace(tzinfo=None) > NOT_BEFORE:
                # set user in onboarding mode
                await member.add_roles(self.onboarding_role)
                # TODO: if done above simplify message here too
                # also send welcome and
                await member.send(self.get_welcome_text(member))
                # also sending the buttons
                await self.send_onboarding_message(member)
                i += 1

            # member has onboarding and interaction is timed out
            if self.onboarding_role in member.roles:
                private_chat = member.dm_channel
                # no private chat yet, let's send the message
                if private_chat is None:
                    await self.send_onboarding_message(member)
                    continue

                # check if latest interaction is time out
                async for message in private_chat.history(limit=20):
                    # walk chat until we hit an interaction
                    interaction = message.interaction
                    if interaction:
                        # if this interaction is expired we send a new one
                        if interaction.is_expired():
                            logger.info(f"Sent new interaction message to {member.id}")
                            await self.send_onboarding_message(member)
                            j += 1
                        # we're done with that user as soon as we hit one interaction
                        break

        if i > 0:
            logger.info(f"Verified {i} member that accepted the rules but didn't get the roles")

        if j > 0:
            logger.info(f"Sent {j} members new interaction message")

    def get_welcome_text(self, member: discord.Member):
        return (f"Hey {member.display_name}, willkommen auf dem _{self.guild.name}_ Discord!\n"
                f"\n"
                "Bei Fragen kannst du dich jederzeit an uns wenden.\n"
                "~Die Serverleitung")


async def setup(bot: commands.Bot):
    await bot.add_cog(VerificationListener(bot))
