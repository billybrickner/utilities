#! /usr/bin/env python3

import time, random, argparse


def getNextChoice(choices):
   return input("\toption %2d:" % (len(choices) + 1))

def prettyPrint(choices):
   print("Choices: " + ", ".join(choices))

def roll(choices):
   loserMessages = ["went out for a pack of cigarettes",
                     "took a long walk off a short pier",
                     "is now using the pronouns was/were",
                     "is just resting",
                     "did their own research and found a cure for COVID",
                     "is pinin' for the Fjords",
                     "is living on a farm upstate",
                     "... press F in the chat",
                     "claimed their final reward",
                     "didn't wake up after September ended",
                     "has gone west",
                     "is now apart of a graveyard smash",
                     "exited stage down",
                     "is now at room temperature",
                     "became a root inspector",
                     "has invested in a pine condo",
                     "is definitely done dancing",
                     "has gone home feet first",
                     "has just invited their friends and family to a necktie social",
                     "is calling collect from the horizontal phone booth",
                     "just got stamped \"return to sender\"",
                     "kicked the oxygen habit",
                     "is picking turnips with a stepladder",
                     "was terminated",
                     "was eliminated",
                     "died to doomblade",
                     "was murdered",
                     "was the victim of a heartless act",
                     "incurred a fatal push",
                     "is not a dead ringer",
                     "was WASTED",
                     "just got done starring in a slasher film",
                     "has a date with Charon",
                     "is now SANS UNDERTALE",
                     "was on the ground when the bodies hit the floor",
                     "got a game over",
                     "reenacted the history the confederacy very quickly",
                     "is getting picked up by Mori Calliope later",
                     "reenacted president Lincoln's final play",
                     "reenacted JFK's drive through downtown",
                     "has their own personal greek choir",
                     "pulled the plug"]

   print("rolling",end="", flush=True)
   for i in range(3):
      time.sleep(0.6)
      print(".", end="",flush=True)
   choice = choices.pop(random.randrange(len(choices)))
   message = loserMessages[random.randrange(len(loserMessages))]
   print("\n\"%s\" %s" % (choice, message))
   time.sleep(2)

def getChoices():
   choices = []

   print("Enter your choices:")

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

def main():
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

if __name__ == '__main__':
   main()



