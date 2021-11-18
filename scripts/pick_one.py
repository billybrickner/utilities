#! /usr/bin/env python3

import time, random, argparse, os



def getMessages(filename):
   with open(filename, 'r') as f:
      messages = [line.strip() for line in f]
   return messages

def getNextChoice(choices):
   return input("\toption %2d:" % (len(choices) + 1))

def prettyPrint(choices):
   choices = [choice.strip() for choice in choices]
   choices = [choice.replace(" ","_") for choice in choices]
   print("Choices: " + " ".join(choices))

def roll(choices):
   path_to_loser_messages = str(os.environ["HOME"]) + "/utilities/profiles/loserMessages.txt"
   loserMessages = getMessages(path_to_loser_messages)

   print("rolling",end="", flush=True)
   for i in range(3):
      time.sleep(0.6)
      print(".", end="",flush=True)
   choice = choices.pop(random.randrange(len(choices)))
   message = loserMessages[random.randrange(len(loserMessages))]
   print("\n\"%s\" %s" % (choice, message))
   time.sleep(2)

def getChoices():

   print("Enter your choices:")

   path_to_defaults = str(os.environ['HOME']) + '/utilities/profiles/defaultChoices.txt'
   choices = getMessages(path_to_defaults)
   for i, choice in enumerate(choices):
        print("\toption %2d: %s" % (i + 1, choice))

   choice = getNextChoice(choices)
   while ((choice != "") or (len(choices) < 2)):
      if (choice != ""):
         choices += [choice]
      else:
         print("Try again")
         print(choices)
      choice = getNextChoice(choices)

   return choices


def getCmdLineChoices():
   parser = argparse.ArgumentParser(description='Process some integers.')
   parser.add_argument('choices', metavar='choices', nargs='*', default='',
                    help='choices to choose from. Space delimited.')
   args = parser.parse_args()
   print(args.choices)
   return args.choices

def pickOne():
   choices = getCmdLineChoices()

   if len(choices) < 2:
      choices = getChoices()

   prettyPrint(choices)
   while len(choices) > 1:
      roll(choices)
      if (len(choices) % 5 == 0):
         print()
         prettyPrint(choices)

   print("Winner:", choices[0])

def main():
   pickOne()

if __name__ == '__main__':
   main()



