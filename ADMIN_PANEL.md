# Admin Panel / Runtime Controls

Open `/admin` as an admin. Runtime switches are stored in MongoDB (`admin_database.bot_settings`), so normal feature changes do not require editing Koyeb environment variables.

## Default referral credit
- 5 Premium/Reward points per qualified referral
- Qualification: referred user completes a successful movie search
- 20 points = 10 Premium days
- Points are not cash and are redeemed only for Premium credit

Admin shortcuts:
- `/refreward POINTS`
- `/refredeem POINTS DAYS`
- `/setskip NUMBER`

## Channel setup
In Admin Panel → Channels, choose a channel setting and then forward any message from the target channel to the bot. The bot checks that it can access the channel before saving the ID.

## Indexing checkpoint
After a successful indexing run, the source channel's latest processed message ID is saved per channel. Future indexing uses that checkpoint instead of starting from the beginning.
