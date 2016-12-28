#!/usr/bin/perl

# Copyright 2016 Christian Fenzl, christiantf@gmx.at
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
# 
#     http://www.apache.org/licenses/LICENSE-2.0
# 
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.


##########################################################################
# Modules
##########################################################################

use CGI;
use CGI::Carp qw(fatalsToBrowser);
use CGI qw/:standard/;
use LWP::UserAgent;
use String::Escape qw( unquotemeta );
use Config::Simple;
use File::HomeDir;
use Cwd 'abs_path';
use URI::Escape;
use XML::Simple qw(:strict);
use warnings;

# Christian Import
use XML::LibXML;
use File::stat;
use File::Basename;
use Time::localtime;
use HTML::Entities;
# Debug
use Time::HiRes qw/ time sleep /;

# Set maximum file upload to approx. 7 MB
# $CGI::POST_MAX = 1024 * 10000;



#use strict;
#no strict "refs"; # we need it for template system
our $namef;
our $value;
our @query;
our @fields;
our @lines;
my $home = File::HomeDir->my_home;
our %cfg_mslist;
our $upload_message;
our $stattable;
our %lox_statsobject;
		

##########################################################################
# Read Settings
##########################################################################

# Version of this script
$version = "0.1.1";

# Figure out in which subfolder we are installed
our $psubfolder = abs_path($0);
$psubfolder =~ s/(.*)\/(.*)\/(.*)$/$2/g;

my  $cfg             = new Config::Simple("$home/config/system/general.cfg");
our $installfolder   = $cfg->param("BASE.INSTALLFOLDER");
our $lang            = $cfg->param("BASE.LANG");
our $miniservercount = $cfg->param("BASE.MINISERVERS");
our $clouddnsaddress = $cfg->param("BASE.CLOUDDNS");
our $curlbin         = $cfg->param("BINARIES.CURL");
our $grepbin         = $cfg->param("BINARIES.GREP");
our $awkbin          = $cfg->param("BINARIES.AWK");

# Generate MS table with IP as key
for (my $msnr = 1; $msnr <= $miniservercount; $msnr++) {
	$cfg_mslist{$cfg->param("MINISERVER$msnr.IPADDRESS")} = $msnr;
}

#########################################################################
# Parameter
#########################################################################

# Everything from URL
foreach (split(/&/,$ENV{'QUERY_STRING'}))
{
  ($namef,$value) = split(/=/,$_,2);
  $namef =~ tr/+/ /;
  $namef =~ s/%([a-fA-F0-9][a-fA-F0-9])/pack("C", hex($1))/eg;
  $value =~ tr/+/ /;
  $value =~ s/%([a-fA-F0-9][a-fA-F0-9])/pack("C", hex($1))/eg;
  $query{$namef} = $value;
}

# Set parameters coming in - get over post
  if ( !$query{'saveformdata'} ) { 
	if ( param('saveformdata') ) { 
		our $saveformdata = quotemeta(param('saveformdata')); 
	} else { 
		our $saveformdata = 0;
	} 
  } else { 
	our $saveformdata = quotemeta($query{'saveformdata'}); 
}

if ( !$query{'lang'} ) {
	if ( param('lang') ) {
		$lang = quotemeta(param('lang'));
	} else {
		$lang = "de";
	}
} else {
	$lang = quotemeta($query{'lang'}); 
}

# Clean up saveformdata variable
$saveformdata =~ tr/0-1//cd;
$saveformdata = substr($saveformdata,0,1);

# Init Language
# Clean up lang variable
$lang =~ tr/a-z//cd;
$lang = substr($lang,0,2);

# If there's no language phrases file for choosed language, use german as default
if (!-e "$installfolder/templates/plugins/$psubfolder/$lang/language.dat") {
	$lang = "de";
}

# Read translations / phrases
our $planguagefile = "$installfolder/templates/plugins/$psubfolder/$lang/language.dat";
our $pphrase = new Config::Simple($planguagefile);

# Default file for reading and writing LoxPLAN file
our $loxconfig_path = "$installfolder/data/plugins/$psubfolder/upload.loxplan";

##########################################################################
# Main program
##########################################################################

our $post = new CGI;

if ( $post->param('Upload') ) {
	saveloxplan();
	form();
	
} elsif ($saveformdata) {
  &save;
} else {
  &form;
}

exit;

#####################################################
# 
# Subroutines
#
#####################################################

#####################################################
# Form-Sub
#####################################################

sub form {

	# Prepare the form
	
	# Check if a .LoxPLAN is already available
	
	
	if ( -e $loxconfig_path ) {
		my $loxplan_modified = ctime(stat($loxconfig_path)->mtime);
		readloxplan();
		$upload_message = "Die aktuell hochgeladene Loxone-Konfiguration ist von $loxplan_modified. Du kannst eine neuere Version hochladen, oder diese verwenden.";
	} else {
		$upload_message = "Lade deine Loxone Konfiguration hoch. Daraus wird ausgelesen, welche Statistiken du aktuell aktiviert hast.";
	}

	# Read Stat definitions and prepare dropdown string
	# UNFINISHED
	our $statdef_dropdown;
	$statdef_dropdown = '
		<select data-mini="true" name="statdef">
			<option selected>Standard</option>
			<option>Definition 1</option>
			<option>Definition 2</option>
			<option>Definition 3</option>
			<option>Definition 4</option>
		</select>';
	
	
	
	generate_import_table();
		
	
	# Print the template
	print "Content-Type: text/html\n\n";
	
	$template_title = $pphrase->param("TXT0000") . ": " . $pphrase->param("TXT0001");
	
	# Print Upload Template
	&lbheader;
	open(F,"$installfolder/templates/plugins/$psubfolder/multi/loxplan_uploadform.html") || die "Missing template plugins/$psubfolder/multi/loxplan_uploadform.html";
	  while (<F>) 
	  {
	    $_ =~ s/<!--\$(.*?)-->/${$1}/g;
	    print $_;
	  }
	close(F);

	# Print table Template
	
	open(F,"$installfolder/templates/plugins/$psubfolder/multi/import_selection.html") || die "Missing template plugins/$psubfolder/multi/import_selection.html";
	  while (<F>) 
	  {
		$_ =~ s/<!--\$(.*?)-->/${$1}/g;
#	    $_ =~ s/<!--\$(.*?)-->/${$1}/g;
	    print $_;
	  }
	close(F);
	
	
	
	# print table footer Template
	
	
#	open(F,"$installfolder/templates/plugins/$psubfolder/$lang/addstat_end.html") || die "Missing template plugins/$psubfolder/$lang/addstat_end.html";
#	  while (<F>) 
#	  {
#	    $_ =~ s/<!--\$(.*?)-->/${$1}/g;
#	    print $_;
#	  }
#	close(F);
	&footer;
	exit;

}

#####################################################
# Save-Sub
#####################################################

sub save 
{

	# Check values

	my $miniserverip        = $cfg->param("MINISERVER$miniserver.IPADDRESS");
	my $miniserverport      = $cfg->param("MINISERVER$miniserver.PORT");
	my $miniserveradmin     = $cfg->param("MINISERVER$miniserver.ADMIN");
	my $miniserverpass      = $cfg->param("MINISERVER$miniserver.PASS");
	my $miniserverclouddns  = $cfg->param("MINISERVER$miniserver.USECLOUDDNS");
	my $miniservermac       = $cfg->param("MINISERVER$miniserver.CLOUDURL");

	# Use Cloud DNS?
	if ($miniserverclouddns) {
		$output = qx($home/bin/showclouddns.pl $miniservermac);
		@fields = split(/:/,$output);
		$miniserverip   = $fields[0];
		$miniserverport = $fields[1];
	}

	# Print template
	$template_title = $pphrase->param("TXT0000") . " - " . $pphrase->param("TXT0001");
	$message = $pphrase->param("TXT0002");
	$nexturl = "./import.cgi?do=form";

	print "Content-Type: text/html\n\n"; 
	&lbheader;
	open(F,"$installfolder/templates/system/$lang/success.html") || die "Missing template system/$lang/success.html";
	while (<F>) 
	{
		$_ =~ s/<!--\$(.*?)-->/${$1}/g;
		print $_;
	}
	close(F);
	&footer;
	exit;
		
}

#####################################################
# Save Loxplan file
#####################################################

sub saveloxplan
{
	# Funktioniert nicht - $upload-filehandle leer...?!
	my $cgi = new CGI();
	my $upload_filehandle = $cgi->upload('loxplan');
	if (! $upload_filehandle ) {
		print STDERR "ERROR: LoxPLAN Upload - Stream filehandle not created.\n";
		exit (-1);
	}
	if (! open(UPLOADFILE, ">$loxconfig_path" ) ) {
		print STDERR "ERROR: LoxPLAN Upload - cannot open local file handle.\n";
		exit (-1);
	}
	# binmode UPLOADFILE;

	while (<$upload_filehandle>) {
		print UPLOADFILE "$_";
	}
	close $upload_filehandle;
	close UPLOADFILE;
	return;

}


 
 
#####################################################
# Generate HTML Import Table
#####################################################

sub generate_import_table 
{
	foreach my $statsobj (keys %lox_statsobject) {
		# print STDERR $statsobj{Title} . "\n";
		
		# UNFINISHED 
		# Set Statistic Definitions from Michael
		$statdef = "1";
				
		$statstable .= '
			  <tr>
				<td class="tg-yw4l">' . encode_entities($lox_statsobject{$statsobj}{Title}) . '</td>
				<td class="tg-yw4l">' . encode_entities($lox_statsobject{$statsobj}{Desc}) . '</td>
				<td class="tg-yw4l">' . encode_entities($lox_statsobject{$statsobj}{Place}) . '</td>
				<td class="tg-yw4l">' . encode_entities($lox_statsobject{$statsobj}{Category}) . '</td>
				<td class="tg-yw4l">' . $lox_statsobject{$statsobj}{StatsType} . '<input type="hidden" name="statstype_' . $statsobj . '" value="' . $lox_statsobject{$statsobj}{StatsType} . '"></td>
				<td class="tg-yw4l">' . $lox_statsobject{$statsobj}{MinVal} . '<input type="hidden" name="minval_' . $statsobj . '" value="' . $lox_statsobject{$statsobj}{MinVal} . '"></td>
				<td class="tg-yw4l">' . $lox_statsobject{$statsobj}{MaxVal} . '<input type="hidden" name="maxval_' . $statsobj . '" value="' . $lox_statsobject{$statsobj}{MaxVal} . '"></td>
				<td class="tg-yw4l">' . $statdef_dropdown . '<input type="hidden" name="statdef_' . $statsobj . '" value="' . $statdef . '"></td>
				<td class="tg-yw4l"> 
				<input data-mini="true" type="checkbox" name="doimport_' . $statsobj . '" value="import">
				<input type="hidden" name="msnr_' . $statsobj . '" value="' . $lox_statsobject{$statsobj}{MSNr} . '">
				<input type="hidden" name="msip_' . $statsobj . '" value="' . $lox_statsobject{$statsobj}{MSIP} . '">
				</td>
			  </tr>
			';
	}
}


#####################################################
# Read LoxPLAN XML
#####################################################

sub readloxplan
{

	my @loxconfig_xml;
	my %StatTypes;
	my %lox_miniserver;
	my %lox_category;
	my %lox_room;
	

	%StatTypes = ( 	1, "Jede Änderung (max. ein Wert pro Minute)",
					2, "Mittelwert pro Minute",
					3, "Mittelwert pro 5 Minuten",
					4, "Mittelwert pro 10 Minuten",
					5, "Mittelwert pro 30 Minuten",
					6, "Mittelwert pro Stunde",
					7, "Digital/Jede Änderung");

	my $start_run = time();

	# For performance, it would be possibly better to switch from XML::LibXML to XML::Twig

	# Prepare data from LoxPLAN file
	my $parser = XML::LibXML->new();
	my $lox_xml = $parser->parse_file($loxconfig_path);
	if (! $lox_xml) {
		print STDERR "import.cgi: Cannot parse LoxPLAN XML file.\n";
		exit(-1);
	}

	# Read Loxone Miniservers
	foreach my $miniserver ($lox_xml->findnodes('//C[@Type="LoxLIVE"]')) {
		# Use an multidimensional associative hash to save a table of necessary MS data
		# key is the Uid
		$lox_miniserver{$miniserver->{U}}{Title} = $miniserver->{Title};
		$lox_miniserver{$miniserver->{U}}{IP} = $miniserver->{IntAddr};
		$lox_miniserver{$miniserver->{U}}{Serial} = $miniserver->{Serial};
		# In a later stage, we have to query the LoxBerry MS Database by IP to get LoxBerrys MS-ID.
	}

	# Read Loxone categories
	foreach my $category ($lox_xml->findnodes('//C[@Type="Category"]')) {
		# Key is the Uid
		$lox_category{$category->{U}} = $category->{Title};
	}
	# print "Test Perl associative array: ", $lox_category{"0b2c7aea-007c-0002-0d00000000000000"}, "\r\n";

	# Read Loxone rooms
	foreach my $room ($lox_xml->findnodes('//C[@Type="Place"]')) {
		# Key is the Uid
		$lox_room{$room->{U}} = $room->{Title};
	}

	# Get all objects that have statistics enabled
	foreach my $object ($lox_xml->findnodes('//C[@StatsType]')) {
		# Get Miniserver of this object
		# Nodes with statistics may be a child or sub-child of LoxLive type, or alternatively Ref-er to the LoxLive node. 
		# Therefore, we have to distinguish between connected in some parent, or referred by in some parent.	
		my $ms_ref;
		my $parent = $object;
		do {
			$parent = $parent->parentNode;
		} while ((!$parent->{Ref}) && ($parent->{Type} ne "LoxLIVE"));
		if ($parent->{Type} eq "LoxLIVE") {
			$ms_ref = $parent->{U};
		} else {
			$ms_ref = $parent->{Ref};
		}
		# print "Objekt: ", $object->{Title}, " (StatsType = ", $object->{StatsType}, ") | Miniserver: ", $lox_miniserver{$ms_ref}{Title}, "\r\n";
		$lox_statsobject{$object->{U}}{Title} = $object->{Title};
		if (defined $object->{Desc}) {
			$lox_statsobject{$object->{U}}{Desc} = $object->{Desc}; }
		else {
			$lox_statsobject{$object->{U}}{Desc} = $object->{Title} . " (*)"; 
		}
		$lox_statsobject{$object->{U}}{StatsType} = $object->{StatsType};
		$lox_statsobject{$object->{U}}{Type} = $object->{Type};
		$lox_statsobject{$object->{U}}{MSName} = $lox_miniserver{$ms_ref}{Title};
		$lox_statsobject{$object->{U}}{MSIP} = $lox_miniserver{$ms_ref}{IP};
		$lox_statsobject{$object->{U}}{MSNr} = $cfg_mslist{$lox_miniserver{$ms_ref}{IP}};
		
		# Place and Category
		my @iodata = $object->getElementsByTagName("IoData");
		# print STDERR "Cat: ", $lox_category{$iodata[0]->{Cr}}, "\r\n";
		$lox_statsobject{$object->{U}}{Category} = $lox_category{$iodata[0]->{Cr}};
		$lox_statsobject{$object->{U}}{Place} = $lox_room{$iodata[0]->{Pr}};
		
		# Min/Max values
		if ($object->{Analog} ne "true") {
			$lox_statsobject{$object->{U}}{MinVal} = 0;
			$lox_statsobject{$object->{U}}{MaxVal} = 1;
		} else {
			if ($object->{MinVal}) { 
				$lox_statsobject{$object->{U}}{MinVal} = $object->{MinVal};
			} else {
				$lox_statsobject{$object->{U}}{MinVal} = "U";
			}
			if ($object->{MaxVal}) { 
				$lox_statsobject{$object->{U}}{MaxVal} = $object->{MaxVal};
			} else {
				$lox_statsobject{$object->{U}}{MaxVal} = "U";
			}
		}
		print STDERR "Object Name: " . $lox_statsobject{$object->{U}}{Title} . "\n";
	}
	
	my $end_run = time();
	my $run_time = $end_run - $start_run;
	# print "Job took $run_time seconds\n";
	return;
}

#####################################################
# Error-Sub
#####################################################

sub error 
{
	$template_title = $pphrase->param("TXT0000") . " - " . $pphrase->param("TXT0001");
	print "Content-Type: text/html\n\n"; 
	&lbheader;
	open(F,"$installfolder/templates/system/$lang/error.html") || die "Missing template system/$lang/error.html";
	while (<F>) 
	{
		$_ =~ s/<!--\$(.*?)-->/${$1}/g;
		print $_;
	}
	close(F);
	&footer;
	exit;
}

#####################################################
# Page-Header-Sub
#####################################################

	sub lbheader 
	{
	  # Create Help page
	  our $helplink = "http://www.loxwiki.eu:80/x/uYCm";
	  open(F,"$installfolder/templates/plugins/$psubfolder/$lang/help.html") || die "Missing template plugins/$psubfolder/$lang/help.html";
	    my @help = <F>;
 	    our $helptext;
	    foreach (@help)
	    {
	      s/[\n\r]/ /g;
	      $_ =~ s/<!--\$(.*?)-->/${$1}/g;
	      $helptext = $helptext . $_;
	    }
	  close(F);
	  open(F,"$installfolder/templates/system/$lang/header.html") || die "Missing template system/$lang/header.html";
	    while (<F>) 
	    {
	      $_ =~ s/<!--\$(.*?)-->/${$1}/g;
	      print $_;
	    }
	  close(F);
	}

#####################################################
# Footer
#####################################################

	sub footer 
	{
	  open(F,"$installfolder/templates/system/$lang/footer.html") || die "Missing template system/$lang/footer.html";
	    while (<F>) 
	    {
	      $_ =~ s/<!--\$(.*?)-->/${$1}/g;
	      print $_;
	    }
	  close(F);
	}
