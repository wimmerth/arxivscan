import arxiv
from email.message import EmailMessage
import smtplib
import json
import os
import enum
from datetime import datetime, timedelta
import argparse
import re

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
            with open("config.json", "w") as f:
                json.dump(self.config, f)

    def register_personal_details(self, name, email, notification_schedule, email_title=None):
        if email_title is None:
            email_title = "New Papers in Your Interest Area"
        self.config["name"] = name
        self.config["email"] = email
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
        self.config["notification_schedule"] = frequency
        self.save_config = True

    def sendQuery(self):
        if "lastUpdate" in self.config:
            lastUpdate = datetime.strptime(self.config["lastUpdate"], "%Y%m%d%H%M")
            if datetime.today() - lastUpdate < timedelta(days=self.config["notification_schedule"]):
                print("Not time to update yet!")
                return
        if "notification_schedule" in self.config:
            date_start, date_end = convert_date(self.config["notification_schedule"])
            if "lastUpdate" in self.config:
                date_start = self.config["lastUpdate"]
            query = f'submittedDate:[{date_start} TO {date_end}] AND ('
        else:
            query = '('
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

        for r in self.client.results(search):
            print(r.title)

        self.send_email(searchResults)
        self.config["lastUpdate"] = datetime.today().strftime("%Y%m%d%H%M")
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
                    <h2 style="font-family:Georgia, 'Times New Roman', Times, serif;color:#454349;">Hi {name}, here is your arXiv update!</h2>
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
    data_start = datetime.today() - timedelta(days=lookback_days)
    date_end = datetime.today()
    return data_start.strftime("%Y%m%d%H%M"), date_end.strftime("%Y%m%d%H%M")


if __name__ == "__main__":
    if not client_email or not client_password:
        print("Please set the environment variables ARXIVSCAN_EMAIL and ARXIVSCAN_PASSWORD")
        exit(1)

    parser = argparse.ArgumentParser(description="Arxiv Scanner")
    parser.add_argument("--config", help="Path to config file")
    parser.add_argument("--interests", help="Add new interests", action=argparse.BooleanOptionalAction)

    args = parser.parse_args()
    arxivClient = ArxivScannerClient(args.config or "config.json")
    if arxivClient.config == {}:
        name = input("Enter your name: ")
        while name == "":
            name = input("Enter your name: ")
        email = input("Enter your email address: ")
        # check for valid email address
        while re.match(r"[^@]+@[^@]+\.[^@]+", email) is None:
            email = input("Enter a VALID email address: ")
        notification_schedule = input("How often would you like to be notified? (frequency in days): ")
        while notification_schedule == "" or not notification_schedule.replace(".", "").isnumeric():
            notification_schedule = input("How often would you like to be notified? (frequency in days): ")
        notification_schedule = float(notification_schedule)
        email_title = input("Enter a title for the notification email (optional): ")
        arxivClient.register_personal_details(name, email, notification_schedule,
                                              email_title if email_title != "" else None)
        interest = input("Enter an interest in the form 'category:query': ")
        while interest != "":
            arxivClient.register_new_interest(interest)
            interest = input("Enter an interest in the form 'category:query': ")
    elif args.interests:
        interest = input("Enter an interest in the form 'category:query': ")
        while interest != "":
            arxivClient.register_new_interest(interest)
            interest = input("Enter an interest in the form 'category:query': ")
    arxivClient.sendQuery()
    arxivClient.close()
