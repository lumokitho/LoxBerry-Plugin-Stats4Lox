#!/usr/bin/perl

# Copyright 2016-2017 Christian Fenzl, christiantf@gmx.at
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
use Config::Simple;
use Cwd 'abs_path';
use File::Basename;
use File::HomeDir;
use File::Path qw(make_path);
use File::stat;
use HTML::Entities;
use HTTP::Request;
use LWP::UserAgent;
use POSIX qw(strftime);
use String::Escape qw( unquotemeta );
use Time::HiRes qw/ time sleep /;
use DateTime;
use URI::Escape;
use warnings;
use XML::LibXML;
use XML::Simple qw(:strict);

# Christian Import
# use Time::localtime;
# Debug

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

# Logfile
our $logfilepath; 
our $lf;
our @loglevels;
our $loglevel=4;

# Use loglevel with care! DEBUG=4 really fills up logfile. Use ERRORS=1 or WARNINGS=2, or disable with 0.
# To log everything to STDERR, use $loglevel=5.

our %StatTypes = ( 	1, "Jede Änderung (max. ein Wert pro Minute)",
					2, "Mittelwert pro Minute",
					3, "Mittelwert pro 5 Minuten",
					4, "Mittelwert pro 10 Minuten",
					5, "Mittelwert pro 30 Minuten",
					6, "Mittelwert pro Stunde",
					7, "Digital/Jede Änderung");		

##########################################################################
# Read Settings
##########################################################################

# Version of this script
$version = "0.1.2";

# Figure out in which subfolder we are installed
our $psubfolder = abs_path($0);
$psubfolder =~ s/(.*)\/(.*)\/(.*)$/$2/g;

$logfilepath = "$home/log/plugins/$psubfolder/import_cgi.log";
openlogfile();
logger(4, "Logfile $logfilepath opened");

our $job_basepath = "$home/data/plugins/$psubfolder/import";

my  $cfg             = new Config::Simple("$home/config/system/general.cfg");
our $installfolder   = $cfg->param("BASE.INSTALLFOLDER");
our $lang            = $cfg->param("BASE.LANG");
our $miniservercount = $cfg->param("BASE.MINISERVERS");
our $clouddnsaddress = $cfg->param("BASE.CLOUDDNS");
our $curlbin         = $cfg->param("BINARIES.CURL");
our $grepbin         = $cfg->param("BINARIES.GREP");
our $awkbin          = $cfg->param("BINARIES.AWK");
our $timezone		 = $cfg->param("TIMESERVER.ZONE");

# Generate MS table with IP as key
# We need this to have a Loxone-UID -> IP -> Stats-DB matching/key
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

# Save if button save was pressed
if ( param('submitbtn') ) { $doapply = 1; }

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
	
} elsif ($doapply) {
  save();
  form();
} else {
  form();
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
		my $loxchgtime = DateTime->from_epoch ( epoch => stat($loxconfig_path)->mtime, time_zone => $timezone );
		readloxplan();
		$upload_message = "Die zuletzt hochgeladene Loxone-Konfiguration ist von " . $loxchgtime->dmy . " " . $loxchgtime->hms . ". Du kannst eine neuere Version hochladen, oder die zuletzt hochgeladene verwenden.";
	} else {
		$upload_message = "Lade deine Loxone Konfiguration (.loxone bzw. .LoxPlan Datei) hoch. Daraus wird ausgelesen, welche Statistiken du aktuell aktiviert hast.";
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
	
	our $table_linecount = 0;
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

#	my $miniserverip        = $cfg->param("MINISERVER$miniserver.IPADDRESS");
#	my $miniserverport      = $cfg->param("MINISERVER$miniserver.PORT");
#	my $miniserveradmin     = $cfg->param("MINISERVER$miniserver.ADMIN");
#	my $miniserverpass      = $cfg->param("MINISERVER$miniserver.PASS");
#	my $miniserverclouddns  = $cfg->param("MINISERVER$miniserver.USECLOUDDNS");
#	my $miniservermac       = $cfg->param("MINISERVER$miniserver.CLOUDURL");

#	# Use Cloud DNS?
#	if ($miniserverclouddns) {
#		$output = qx($home/bin/showclouddns.pl $miniservermac);
#		@fields = split(/:/,$output);
#		$miniserverip   = $fields[0];
#		$miniserverport = $fields[1];
#	}

#	# Print template
#	$template_title = $pphrase->param("TXT0000") . " - " . $pphrase->param("TXT0001");
#	$message = $pphrase->param("TXT0002");
#	$nexturl = "./import.cgi?do=form";
#
#	print "Content-Type: text/html\n\n"; 
#	&lbheader;
#	open(F,"$installfolder/templates/system/$lang/success.html") || die "Missing template system/$lang/success.html";
#	while (<F>) 
#	{
#		$_ =~ s/<!--\$(.*?)-->/${$1}/g;
#		print $_;
#	}
#	close(F);
#	&footer;

	# On saving form, parse form data and create import jobs in FS
	$form_linenumbers = param("linenumbers");
		
	if ($form_linenumbers <= 0) { 
		logger(2, "Seems to have empty POST data. (Form Linenumbers: " . $form_linenumbers . ")");
		return; 
	}
	
	# Looping through post formdata lines
	
	my $addstat_urlbase = "http://localhost/admin/plugins/$psubfolder/addstat.cgi";
	
	eval { make_path($job_basepath) };
	if ($@) {
		logger(1, "Couldn't create $job_basepath: $@");
	}
	
	
	logger(4, "Stats import path: $job_basepath");
	
	
	for (my $line = 1; $line <= $form_linenumbers; $line++) {
		logger(4, "Line " . $line . ": UID " . param("loxuid_" . $line));
		if ( param("doimport_$line") eq 'import' ) {
			logger(4, "IMPORT Line " . $line . ": UID " . param("loxuid_$line"));
			
			# Call Michaels addstat.cgi by URL to create RRD archive
			my $loxonename = uri_escape( param("title_$line") );
			my $loxuid = param("loxuid_$line");
			my $statstype = param("statstype_$line");
			my $description = uri_escape( param("desc_$line") . " (" . $loxuid . ")" );
			# settings need some code to get dbsettings.datfrom Michael
			my $settings = "";
			my $minval = param("minval_$line");
			my $maxval = param("maxval_$line");
			my $place = uri_escape( param("place_$line") );
			my $category = uri_escape( param("category_$line") );
			my $stat_ms = param("msnr_$line");
			# URI-Escape has to be undone when writing the job!
			
			my $statfullurl = $addstat_urlbase . "?script=1&loxonename=$loxonename&description=$description&settings=$settings&miniserver=$stat_ms&minval=$minval&maxval=$maxval&place=$place&category=$category&uid=$loxuid";
			logger(4, "addstat URL " . $statfullurl);
			 

# Michael is changing the addstat interface from web call to local execution
			 # HTTP Request
			# logger (4, "UA Instance");
			my $ua = LWP::UserAgent->new;
			# logger (4, "REQ Instance");
			#my $req = HTTP::Request->new(GET => $statfullurl);
			# $req->header('content-type' => 'application/json');
			# $req->header('x-auth-token' => 'kfksj48sdfj4jd9d');
			 
			# logger (4, "RESP Instance");
			my $resp = $ua->get($statfullurl);
			# logger (4, "IF Instance " . $resp->decoded_content );
			
			if ($resp->is_success) {
				my $message = $resp->decoded_content;
				logger (3, "Successful addstat http request");
				logger (4, "HTTP reply: " . $message);
				
				# Format addstat response to get useful output
				my @stat_message = split /\+/, $message;
				logger(4, "Resp_Status: $stat_message[3] Resp_Text $stat_message[6] Resp_DBID $stat_message[9]");
				my $resp_status = $stat_message[3];
				my $resp_message = $stat_message[6];
				my $resp_dbnr = $stat_message[9];
				if ($resp_status eq "OK" && $resp_dbnr > 0) {
					logger(3, "addstat - RRD successfully created with DB-Nr $resp_dbnr");
					# Addstat successfully called 
					
					# Check if a job is already running
					if (! glob("$job_basepath/$loxuid.running.*" )) {
						# Not running - create job
						$job = new Config::Simple(syntax=>'ini');
						$job->param("loxonename", 	uri_unescape($loxonename));
						$job->param("loxuid", 		$loxuid);
						$job->param("statstype", 	$statstype);
						$job->param("description", 	uri_unescape($description));
						$job->param("settings",		$settings);
						$job->param("minval",		$minval);
						$job->param("maxval",		$maxval);
						$job->param("place",		uri_unescape($place));
						$job->param("category",		uri_unescape($category));
						$job->param("ms_nr",		$stat_ms);
						$job->param("db_nr",		$resp_dbnr);
						$job->param("import_epoch",	"0");
						$job->param("useramdisk",	"Fast");
						$job->param("loglevel",		"4");
						$job->param("Last status",	"Scheduled");
						$job->param("try",			"1");
						$job->param("maxtries",		"5");

						$job->write("$job_basepath/$loxuid.job") or logger (1, "Could not create job file for $loxonename with DB number $resp_dbnr");
						undef $job;
					} else { 
						# Running state - do not create new job
						logger (2, "Job $loxonename ($loxuid) is currently in 'Running' state and will not be created again.");
					}
				} else {
					# Addstat running but failed
					logger(2, "addstat not successfully. Returned $resp_status - $resp_message");
				}
			} else {
				# Addstat URL Call failed
				logger(1, "Calling addstat URL returns an error:");
				logger(1, "HTTP GET error: " . $resp->code . " " . $resp->message);
			}
		# End of activated lines loop
		}
	# End of lines loop
	}
	# For debugging, quit everything (will generate an error 500)
	# exit;
		
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
		logger(1, "LoxPLAN Upload - Stream filehandle not created.");
		exit (-1);
	}
	if (! open(UPLOADFILE, ">$loxconfig_path" ) ) {
		logger("ERROR: LoxPLAN Upload - cannot open local file handle.");
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
	# Define Row colors for import state
	my %ImportStates = (
		"none" 		=> "white", 
		"failed" 	=> "#ffa0a0",
		"scheduled"	=> "#d3d3d3",
		"running"	=> "#d9ff1e",
		"finished"	=> "#a2f99d"
		);
	
	# Get job status from file system
	
	my @failedlist = <"$job_basepath/*.failed">;
	my @finishedlist = <"$job_basepath/*.finished">;
	my @joblist = <"$job_basepath/*.job">;
	my @runninglist = <"$job_basepath/*.running.*">;
	
	foreach my $job (@failedlist) {
	
		my $jobname = get_jobname_from_filename($job);
		if (exists $lox_statsobject{$jobname}) {
			$lox_statsobject{$jobname}{TableColor} = $ImportStates{'failed'};
		}
	}
	foreach my $job (@finishedlist) {
	
		my $jobname = get_jobname_from_filename($job);
		if (exists $lox_statsobject{$jobname}) {
			$lox_statsobject{$jobname}{TableColor} = $ImportStates{'finished'};
		}
	}
	foreach my $job (@joblist) {
	
		my $jobname = get_jobname_from_filename($job);
		if (exists $lox_statsobject{$jobname}) {
			$lox_statsobject{$jobname}{TableColor} = $ImportStates{'scheduled'};
		}
	}
	foreach my $job (@runninglist) {
	
		my $jobname = get_jobname_from_filename($job);
		if (exists $lox_statsobject{$jobname}) {
			$lox_statsobject{$jobname}{TableColor} = $ImportStates{'running'};
		}
	}
		
	# Loop the statistic objects
	foreach my $statsobj (keys %lox_statsobject) {
		$table_linecount = $table_linecount + 1;
			
		# logger (4, $statsobj{Title});
		# UNFINISHED 
		# Set Statistic Definitions from Michael
		$statdef = "1";
		
		if (! $lox_statsobject{$statsobj}{TableColor}) {
			$lox_statsobject{$statsobj}{TableColor} = $ImportStates{'none'};
		}
		
		# Tabellenbug! OFFEN! Farbe wird nicht mitsortiert!
		
		$statstable .= '
			  <tr bgcolor="' . $lox_statsobject{$statsobj}{TableColor} . '">
				<td class="tg-yw4l">' . encode_entities($lox_statsobject{$statsobj}{Title}) . '<input type="hidden" name="title_' . $table_linecount . '" value="' . encode_entities($lox_statsobject{$statsobj}{Title}) . '"></td>
				<td class="tg-yw4l">' . encode_entities($lox_statsobject{$statsobj}{Desc}) . '<input type="hidden" name="desc_' . $table_linecount . '" value="' . encode_entities($lox_statsobject{$statsobj}{Desc}) . '"></td>
				<td class="tg-yw4l">' . encode_entities($lox_statsobject{$statsobj}{Place}) . '<input type="hidden" name="place_' . $table_linecount . '" value="' . encode_entities($lox_statsobject{$statsobj}{Place}) . '"></td>
				<td class="tg-yw4l">' . encode_entities($lox_statsobject{$statsobj}{Category}) . '<input type="hidden" name="category_' . $table_linecount . '" value="' . encode_entities($lox_statsobject{$statsobj}{Category}) . '"></td>
				<td align="center" class="tg-yw4l" title="' . $StatTypes{$lox_statsobject{$statsobj}{StatsType}} . '"><div class="tooltip">' . $lox_statsobject{$statsobj}{StatsType} .  '</div><input type="hidden" name="statstype_' . $table_linecount . '" value="' . $lox_statsobject{$statsobj}{StatsType} . '"></td>
				<td align="center" class="tg-yw4l">' . $lox_statsobject{$statsobj}{MinVal} . '<input type="hidden" name="minval_' . $table_linecount . '" value="' . $lox_statsobject{$statsobj}{MinVal} . '"></td>
				<td align="center" class="tg-yw4l">' . $lox_statsobject{$statsobj}{MaxVal} . '<input type="hidden" name="maxval_' . $table_linecount . '" value="' . $lox_statsobject{$statsobj}{MaxVal} . '"></td>
				<td class="tg-yw4l">' . $statdef_dropdown . '<input type="hidden" name="statdef_' . $table_linecount . '" value="' . $statdef . '"></td>
				<td align="center" class="tg-yw4l"> 
				<input data-mini="true" type="checkbox" name="doimport_' . $table_linecount . '" value="import">
				<input type="hidden" name="msnr_' . $table_linecount . '" value="' . $lox_statsobject{$statsobj}{MSNr} . '">
				<input type="hidden" name="msip_' . $table_linecount . '" value="' . $lox_statsobject{$statsobj}{MSIP} . '">
				<input type="hidden" name="loxuid_' . $table_linecount . '" value="' . $statsobj . '">
				</td>
			  </tr>
			';
	}
}

# Return Job name from filename
sub get_jobname_from_filename
{
	my($jobpath) = @_;
	my($filename, $dirs, $suffix) = fileparse($jobpath);
	return (split /\./, $filename)[0];
}




#####################################################
# Read LoxPLAN XML
#####################################################

sub readloxplan
{

	my @loxconfig_xml;
	my %lox_miniserver;
	my %lox_category;
	my %lox_room;
	my $start_run = time();

	# For performance, it would be possibly better to switch from XML::LibXML to XML::Twig

	# Prepare data from LoxPLAN file
	my $parser = XML::LibXML->new();
	my $lox_xml = $parser->parse_file($loxconfig_path);
	if (! $lox_xml) {
		logger(1, "import.cgi: Cannot parse LoxPLAN XML file.");
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
		logger (4, "Objekt: " . $object->{Title} . " (StatsType = " . $object->{StatsType} . ") | Miniserver: " . $lox_miniserver{$ms_ref}{Title});
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
		logger (4, "Cat: " . $lox_category{$iodata[0]->{Cr}});
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
		logger(4, "Object Name: " . $lox_statsobject{$object->{U}}{Title});
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

#####################################################
# Logging
#####################################################

# Log Levels
# 0 Nothing is logged
# 1 Errors only
# 2 Including warnings
# 3 Including infos
# 4 Full debug
# 5 Send everything to STDERR

	sub openlogfile
	{
		if ( $loglevel > 0 ) {
			open $lf, ">>", $logfilepath
				or do {
					# If logfile cannot be created, change loglevel to 5 (STDERR)
					print STDERR "ERROR: Stats4Lox Import - Could not create logfile $logfilepath";
					$loglevel = 5;
				}
		}
		@loglevels = ("NOLOG", "ERROR", "WARNING", "INFO", "DEBUG");
	}

	sub logger 
	{
		my ($level, $message) = @_;
		
		if ( $loglevel == 5 ) {
			($sec,$min,$hour,$mday,$mon,$year,$wday,$yday,$isdst) = CORE::localtime(time);
			my $now_string = sprintf("%04d-%02d-%02d %02d:%02d:%02d", $year+1900, $mon+1, $mday, $hour, $min, $sec);
			print STDERR "$now_string Stats4Lox import.cgi $loglevels[$level]: $message\r\n";
		} elsif ( $level <= $loglevel && $loglevel <= 4) {
			($sec,$min,$hour,$mday,$mon,$year,$wday,$yday,$isdst) = CORE::localtime(time);
			my $now_string = sprintf("%04d-%02d-%02d %02d:%02d:%02d", $year+1900, $mon+1, $mday, $hour, $min, $sec);
			print $lf "$now_string $loglevels[$level]: $message\r\n";
		}
	}
	