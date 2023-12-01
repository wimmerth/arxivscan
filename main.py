import arxiv
from email.message import EmailMessage
import smtplib
import json
import os
import enum
from datetime import datetime, timedelta, timezone
import argparse
import re
from urllib import request

client_email = os.environ.get("ARXIVSCAN_EMAIL")
client_password = os.environ.get("ARXIVSCAN_PASSWORD")


class QueryCategory(str, enum.Enum):
    title = "ti"
    abstract = "abs"
    author = "au"
    comment = "co"
    journalreference = "jr"
    subjectcategory = "cat"
    reportnumber = "rn"
    all = "all"


class ArxivScannerClient:

    def __init__(self, config_file):
        self.config_file = config_file
        self.save_config = False
        self.client = arxiv.Client()

        if config_file and os.path.exists(config_file):
            with open(config_file) as f:
                self.config = json.load(f)
        else:
            print("Creating new configuration.")
            self.config = {}
            self.save_config = True

    def close(self):
        if self.save_config:
            with open(self.config_file, "w") as f:
                json.dump(self.config, f)

    def register_personal_details(self, name, email, notification_schedule, email_title=None):
        if email_title is None:
            email_title = "New Papers in Your Interest Area"
        self.config["name"] = name
        self.config["email"] = email
        if notification_schedule > 0:
            self.config["notification_schedule"] = notification_schedule
        self.config["email_title"] = email_title
        self.config["max_results"] = 20
        self.save_config = True

    def register_new_interest(self, interest):
        category, query = parse_interest(interest)
        if category is None or query is None:
            return
        if not "interests" in self.config:
            self.config["interests"] = []
        self.config["interests"].append({"category": category, "query": query})
        self.save_config = True

    def list_interests(self):
        print("ID\tCAT\tQUERY")
        for i, interest in enumerate(self.config["interests"]):
            print(f"{i}\t{interest['category']}\t{interest['query']}")

    def remove_interest(self, interest_id):
        self.config["interests"].pop(interest_id)
        self.save_config = True

    def set_update_frequency(self, frequency):
        if frequency > 0:
            self.config["notification_schedule"] = frequency
            self.save_config = True

    def sendQuery(self):
        if "notification_schedule" in self.config:
            date_start, date_end = convert_date(self.config["notification_schedule"])
            if ("lastUpdate" in self.config and datetime.strptime(self.config["lastUpdate"],
                                                                  "%Y%m%d%H%M") > date_end - timedelta(
                days=self.config["notification_schedule"])):
                print("Not time to update yet!")
                return
        else:
            date_start, date_end = convert_date(7)
        date_start = date_start.strftime("%Y%m%d%H%M")
        date_end = date_end.strftime("%Y%m%d%H%M")
        if "lastUpdate" in self.config:
            date_start = self.config["lastUpdate"]
        query = f'submittedDate:[{date_start} TO {date_end}] AND ('

        for interest in self.config["interests"]:
            query += interest["category"] + ':' + f'"{interest["query"]}"' + " OR "
        query = query[:-4]
        query += ")"
        print(query)
        search = arxiv.Search(
            query=query,
            max_results=self.config["max_results"],
            sort_by=arxiv.SortCriterion.SubmittedDate,
            sort_order=arxiv.SortOrder.Descending
        )

        searchResults = self.client.results(search)
        res_counter = 0

        for r in self.client.results(search):
            res_counter += 1
            print(r.title)

        if res_counter > 0:
            self.send_email(searchResults)
        self.config["lastUpdate"] = date_end
        self.save_config = True

    def send_email(self, paper_list):
        # Setup the MIME
        message = EmailMessage()
        message['From'] = client_email
        message['To'] = self.config["email"]
        message['Subject'] = self.config["email_title"]

        # The body and the attachments for the mail
        message.set_content(papers_to_html(self.config["name"], paper_list), subtype='html')

        # Create SMTP session for sending the mail
        with smtplib.SMTP_SSL('smtp.gmail.com', 465) as smtp:
            smtp.login(client_email, client_password)
            smtp.send_message(message)


def papers_to_html(name, paper_list):
    paper_template = '''
    <div style="padding-bottom:20px; padding-left:10px; padding-right: 10px">
        <div>
            <div style="text-align:center;">
                <h3>{}</h3>
                <p>{}</p>
                <p>{}</p>
                <a href="{}">Go to paper page</a>
            </div>
        </div>
    </div>
    <hr>
    '''
    html = f'''
    <!DOCTYPE html>
        <html lang="en">
            <body>
                <div style="background-color:#eee;padding:10px 20px;">
                    <h1 style="color:#454349;">Hi {name}, here is your arXiv update!</h1>
                </div>'''
    for paper in paper_list:
        html += paper_template.format(paper.title, ", ".join([a.name for a in paper.authors]), paper.summary,
                                      paper.entry_id)
    html += "</body></html>"
    return html


def parse_interest(interest):
    interest = interest.split(":")
    category = interest[0].strip().lower()
    if category not in QueryCategory.__members__:
        print("Invalid category! Please choose from the following:")
        for c in QueryCategory.__members__:
            print(c)
        return None, None
    category = QueryCategory[category].value
    query = interest[1]
    return category, query


def convert_date(lookback_days):
    start_date = datetime.utcnow() - timedelta(days=lookback_days)
    end_date = datetime.utcnow()

    start_date_est = start_date - timedelta(hours=-5)
    end_date_est = end_date - timedelta(hours=-5)

    submission_start_date_est = find_last_update_and_submission_slot(start_date_est, start=True)
    submission_end_date_est = find_last_update_and_submission_slot(end_date_est, start=False)

    submission_start_date = submission_start_date_est + timedelta(hours=5)
    submission_end_date = submission_end_date_est + timedelta(hours=5)

    return submission_start_date, submission_end_date


def find_last_update_and_submission_slot(current_date, start=True):
    # Define the days when updates are posted
    update_days = ["Monday", "Tuesday", "Wednesday", "Thursday", "Sunday"]

    # Define the time when updates are posted
    update_time = datetime.strptime("20:00", "%H:%M").time()

    # Check if today is an update day and the current time is after the update time
    if current_date.strftime("%A") in update_days and current_date.time() > update_time:
        # The next update is today at 20:00
        last_update = datetime.combine(current_date.date(), update_time)
    else:
        # Find the most recent update day
        days_back = 1
        while True:
            next_day = current_date - timedelta(days=days_back)
            if next_day.strftime("%A") in update_days:
                break
            days_back += 1

        last_update = datetime.combine(next_day.date(), update_time)

    # Calculate the start of the corresponding submission timeslot
    if last_update.strftime("%A") == "Sunday":
        # thursday at 14:00
        submission_start = last_update - timedelta(days=3 if start else 2, hours=6)
    elif last_update.strftime("%A") == "Monday":
        # friday at 14:00
        submission_start = last_update - timedelta(days=3 if start else 0, hours=6)
    else:
        # the day before at 14:00
        submission_start = last_update - timedelta(days=1 if start else 0, hours=6)

    return submission_start


def internet_on():
    try:
        request.urlopen('https://8.8.8.8', timeout=1)
        return True
    except Exception as err:
        print(err)
        return False


if __name__ == "__main__":
    if not client_email or not client_password:
        print("Please set the environment variables ARXIVSCAN_EMAIL and ARXIVSCAN_PASSWORD")
        exit(1)

    parser = argparse.ArgumentParser(description="Arxiv Scanner")
    parser.add_argument("--config", help="Path to config file")
    parser.add_argument("--interests", help="Add new interests", action=argparse.BooleanOptionalAction)
    parser.add_argument("--on_startup", help="Run script on machine startup", action=argparse.BooleanOptionalAction)

    args = parser.parse_args()
    arxivClient = ArxivScannerClient(args.config or "config.json")
    if arxivClient.config == {}:
        assert not args.on_startup, "Cannot run on startup without a config file!"
        name = input("Enter your name: ")
        while name == "":
            name = input("Enter your name: ")

        email = input("Enter your email address (optional, default: ARXIVSCAN_EMAIL): ")
        # check for valid email address
        while email != "" and re.match(r"[^@]+@[^@]+\.[^@]+", email) is None:
            email = input("Enter a VALID email address: ")
        if email == "":
            email = client_email

        notification_schedule = input("How often would you like to be notified? (frequency in days, optional): ")
        while notification_schedule != "" and not notification_schedule.replace(".", "").isnumeric():
            notification_schedule = input("How often would you like to be notified? (frequency in days, optional): ")
        if notification_schedule == "":
            notification_schedule = -1
        else:
            notification_schedule = float(notification_schedule)

        email_title = input(
            "Enter a title for the notification email (optional, default: New Papers in Your Interest Area): ")
        arxivClient.register_personal_details(name, email, notification_schedule,
                                              email_title if email_title != "" else None)

        interest = input("Enter an interest in the form 'category:query': ")
        while interest != "":
            arxivClient.register_new_interest(interest)
            interest = input("Enter an interest in the form 'category:query': ")

    elif args.interests:
        assert not args.on_startup, "Cannot interactively add interests on startup!"
        interest = input("Enter an interest in the form 'category:query': ")
        while interest != "":
            arxivClient.register_new_interest(interest)
            interest = input("Enter an interest in the form 'category:query': ")

    if args.on_startup:
        import time

        time.sleep(20)
        retry_counter = 0
        while not internet_on():
            time.sleep(10)
            retry_counter += 1
            if retry_counter > 20:
                print("No internet connection found!")
                exit(1)

    arxivClient.sendQuery()
    arxivClient.close()
