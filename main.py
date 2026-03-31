import arxiv
from email.message import EmailMessage
import smtplib
import json
import os
import enum
from datetime import datetime, timedelta
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
        if "interests" in self.config:
            for i, interest in enumerate(self.config["interests"]):
                print(f"{i}\t{interest['category']}\t{interest['query']}")
        else:
            print("No interests registered yet.")

    def remove_interest(self, interest_id):
        self.config["interests"].pop(interest_id)
        self.save_config = True

    def set_update_frequency(self, frequency):
        if frequency > 0:
            self.config["notification_schedule"] = frequency
            self.save_config = True

    def print_status(self):
        print("\n--- ArxivScanner Configuration Status ---")
        print(f"Name:             {self.config.get('name', 'N/A')}")
        print(f"Email:            {self.config.get('email', 'N/A')}")
        print(f"Email Title:      {self.config.get('email_title', 'N/A')}")
        print(f"Update Frequency: {self.config.get('notification_schedule', 'N/A')} days")
        print(f"Last Update:      {self.config.get('lastUpdate', 'Never')}")
        print("\nRegistered Interests:")
        self.list_interests()
        print("-----------------------------------------\n")

    def test_email(self):
        print("Running in test mode. Fetching up to 2 recent papers...")
        if not self.config.get("interests"):
            print("No interests found. Please add interests first.")
            return

        query = "("
        for interest in self.config["interests"]:
            query += interest["category"] + ':' + f'"{interest["query"]}"' + " OR "
        query = query[:-4] + ")"

        search = arxiv.Search(
            query=query,
            max_results=2,
            sort_by=arxiv.SortCriterion.SubmittedDate,
            sort_order=arxiv.SortOrder.Descending
        )

        try:
            results = list(self.client.results(search))
            if results:
                print(f"Found {len(results)} matches for test email. Sending...")
                self.send_email(results, is_test=True)
                print("Test email sent successfully!")
            else:
                print("No recent papers found for your interests even for a test.")
        except Exception as e:
            print(f"Error during test query: {e}")

    def sendQuery(self):
        print("Checking schedule and building query...")
        if "notification_schedule" in self.config:
            date_start, date_end = convert_date(self.config["notification_schedule"])
            if ("lastUpdate" in self.config and datetime.strptime(self.config["lastUpdate"],
                                                                  "%Y%m%d%H%M") > date_end - timedelta(
                days=self.config["notification_schedule"])):
                print("Not time to update yet!")
                return
        else:
            date_start, date_end = convert_date(7)

        date_start_str = date_start.strftime("%Y%m%d%H%M")
        date_end_str = date_end.strftime("%Y%m%d%H%M")

        if "lastUpdate" in self.config:
            date_start_str = self.config["lastUpdate"]

        if date_start_str == date_end_str:
            print("No new updates!")
            return

        query = f'submittedDate:[{date_start_str} TO {date_end_str}] AND ('

        if not self.config.get("interests"):
            print("No interests configured. Skipping query.")
            return

        for interest in self.config["interests"]:
            query += interest["category"] + ':' + f'"{interest["query"]}"' + " OR "
        query = query[:-4]
        query += ")"

        print(f"Querying arXiv API: {query}")
        search = arxiv.Search(
            query=query,
            max_results=self.config.get("max_results", 20),
            sort_by=arxiv.SortCriterion.SubmittedDate,
            sort_order=arxiv.SortOrder.Descending
        )

        try:
            searchResults = list(self.client.results(search))
        except Exception as e:
            print(f"Error fetching results from arXiv API: {e}")
            self.send_error_email(str(e))
            return

        if len(searchResults) > 0:
            print(f"Found {len(searchResults)} new papers. Sending email...")
            for r in searchResults:
                print(f" - {r.title}")
            self.send_email(searchResults)
            print("Email sent successfully.")
        else:
            print("No new papers found in this timeframe.")

        self.config["lastUpdate"] = date_end_str
        self.save_config = True

    def send_email(self, paper_list, is_test=False):
        # Setup the MIME
        message = EmailMessage()
        message['From'] = client_email
        message['To'] = self.config["email"]

        subject = self.config.get("email_title", "New Papers in Your Interest Area")
        if is_test:
            subject = "[TEST] " + subject

        message['Subject'] = subject

        # The body and the attachments for the mail
        message.set_content(papers_to_html(self.config.get("name", "User"), paper_list), subtype='html')

        # Create SMTP session for sending the mail
        with smtplib.SMTP_SSL('smtp.gmail.com', 465) as smtp:
            smtp.login(client_email, client_password)
            smtp.send_message(message)

    def send_error_email(self, error_msg):
        try:
            message = EmailMessage()
            message['From'] = client_email
            message['To'] = self.config["email"]
            message['Subject'] = "ArxivScanner Encountered an Error"
            message.set_content(
                f"Hi {self.config.get('name', 'User')},\n\nArxivScanner encountered an error while querying the API:\n\n{error_msg}\n\nPlease check your configuration or script logs.")
            with smtplib.SMTP_SSL('smtp.gmail.com', 465) as smtp:
                smtp.login(client_email, client_password)
                smtp.send_message(message)
            print("Sent error notification email to user.")
        except Exception as smtp_err:
            print(f"Could not send error email: {smtp_err}")


def extract_urls(text):
    if not text:
        return []
    url_pattern = re.compile(r'https?://[^\s<>"]+|www\.[^\s<>"]+')
    return url_pattern.findall(text)


def papers_to_html(name, paper_list):
    paper_template = '''
    <div style="margin-bottom: 30px; padding-bottom: 20px; border-bottom: 1px solid #eaeaea;">
        <h3 style="margin: 0 0 5px 0; font-size: 18px;">
            <a href="{paper_url}" style="color: #0366d6; text-decoration: none;">{title}</a>
        </h3>
        <p style="margin: 0 0 10px 0; color: #586069; font-size: 14px; font-style: italic;">
            {authors}
        </p>
        <p style="margin: 0 0 15px 0; color: #24292e; font-size: 14px; line-height: 1.5;">
            {summary}
        </p>
        <div style="font-size: 13px; margin-bottom: 10px;">
            <a href="{paper_url}" style="color: #0366d6; text-decoration: none; font-weight: bold; margin-right: 15px;">📄 Abstract</a>
            <a href="{pdf_url}" style="color: #d73a49; text-decoration: none; font-weight: bold; margin-right: 15px;">📥 PDF</a>
            {extra_links_html}
        </div>
        <p style="margin: 0; color: #6a737d; font-size: 12px;">
            Submitted: {date}
            <br>
            {comment_html}
        </p>
    </div>
    '''

    html = f'''
    <!DOCTYPE html>
    <html lang="en">
    <body style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; background-color: #f6f8fa; padding: 20px; margin: 0;">
        <div style="max-width: 650px; margin: 0 auto; background-color: #ffffff; padding: 30px; border-radius: 6px; box-shadow: 0 1px 3px rgba(0,0,0,0.05);">
            <div style="border-bottom: 2px solid #eaeaea; margin-bottom: 25px; padding-bottom: 10px;">
                <h2 style="color: #24292e; margin: 0;">Hi {name},</h2>
                <p style="color: #586069; margin: 5px 0 0 0;">Here are your latest arXiv matches.</p>
            </div>
    '''

    for paper in paper_list:
        combined_text = paper.summary + " " + (paper.comment or "")
        urls = list(set(extract_urls(combined_text)))

        extra_links_html = ""
        for url in urls:
            if "github.com" in url.lower():
                link_label = "🔗 Code"
            else:
                link_label = "🔗 Project Website"
            extra_links_html += f'<a href="{url}" style="color: #28a745; text-decoration: none; font-weight: bold; margin-right: 15px;">{link_label}</a>'

        comment_html = f"Comment: {paper.comment}" if paper.comment else ""
        clean_summary = paper.summary.replace('\n', ' ')

        html += paper_template.format(
            title=paper.title,
            paper_url=paper.entry_id,
            pdf_url=paper.pdf_url,
            authors=", ".join([a.name for a in paper.authors]),
            summary=clean_summary,
            extra_links_html=extra_links_html,
            date=paper.published.strftime("%d %b %Y"),
            comment_html=comment_html
        )

    html += '''
            <div style="margin-top: 30px; text-align: center; color: #6a737d; font-size: 12px;">
                Sent by ArxivScanner
            </div>
        </div>
    </body>
    </html>
    '''
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

    # Fixed Timezone Offset Math: UTC to EST means subtracting 5 hours, not adding them.
    start_date_est = start_date - timedelta(hours=5)
    end_date_est = end_date - timedelta(hours=5)

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
        # Pinging a valid robust domain to avoid raw IP SSL issues on strict networks
        request.urlopen('https://arxiv.org', timeout=3)
        return True
    except Exception as err:
        print(f"Internet connection issue: {err}")
        return False


if __name__ == "__main__":
    if not client_email or not client_password:
        print("Please set the environment variables ARXIVSCAN_EMAIL and ARXIVSCAN_PASSWORD")
        exit(1)

    parser = argparse.ArgumentParser(description="Arxiv Scanner")
    parser.add_argument("--config", help="Path to config file")
    parser.add_argument("--interests", help="Add new interests", action=argparse.BooleanOptionalAction)
    parser.add_argument("--on_startup", help="Run script on machine startup", action=argparse.BooleanOptionalAction)
    parser.add_argument("--status", help="Print current configuration and active queries", action="store_true")
    parser.add_argument("--test-email", help="Send a test email fetching the latest matched papers",
                        action="store_true")

    args = parser.parse_args()
    arxivClient = ArxivScannerClient(args.config or "config.json")

    if args.status:
        arxivClient.print_status()
        arxivClient.close()
        exit(0)

    if arxivClient.config == {}:
        assert not args.on_startup, "Cannot run on startup without a config file!"
        assert not args.test_email, "Cannot run a test email without a configuration!"
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

    if args.test_email:
        arxivClient.test_email()
        arxivClient.close()
        exit(0)

    if args.on_startup:
        import time

        print("Startup delay applied...")
        time.sleep(20)
        retry_counter = 0
        while not internet_on():
            print("Waiting for internet connection...")
            time.sleep(10)
            retry_counter += 1
            if retry_counter > 20:
                print("No internet connection found! Exiting.")
                exit(1)

    arxivClient.sendQuery()
    arxivClient.close()